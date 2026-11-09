"""Review/apply only the two camera settings from course section 9.4.

Default operation is a read-only diff. Apply requires sudo and the SHA256 shown
by the review, preventing a stale review from overwriting a changed boot file.
This helper never reboots and does not open a camera or motor device.
"""

import argparse
import datetime
import difflib
import hashlib
import os
from pathlib import Path
import re
import shutil
import tempfile


def desired_config(text):
    """Return a minimal camera-stack edit without replacing other boot settings."""
    result, count = re.subn(
        r'^camera_auto_detect\s*=\s*\d+\s*$', 'camera_auto_detect=0', text, flags=re.MULTILINE
    )
    if count != 1:
        raise ValueError('Expected exactly one active camera_auto_detect setting')
    starts = re.findall(r'^start_x\s*=.*$', text, flags=re.MULTILINE)
    if starts:
        if starts != ['start_x=1']:
            raise ValueError('Existing start_x setting needs manual review')
    else:
        section = '' if result.rstrip().endswith('[all]') else '\n[all]'
        result = (
            result.rstrip() + section + '\n# CP21 course 9.4: legacy CSI camera stack.\nstart_x=1\n'
        )
    return result


def main():
    """Print the proposed diff, or back up and apply the exact reviewed input."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-sha256')
    args = parser.parse_args()
    model = Path('/proc/device-tree/model').read_text().strip('\x00')
    if not model.startswith('Raspberry Pi 4 Model B'):
        raise SystemExit('This reviewed legacy configuration targets Raspberry Pi 4 only')
    path = Path('/boot/firmware/config.txt')
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    before = raw.decode('utf-8')
    after = desired_config(before)
    print('MODEL:', model)
    print('CURRENT_SHA256:', digest)
    print(
        ''.join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=str(path),
                tofile='proposed-config.txt',
            )
        )
    )
    if not args.apply:
        print('REVIEW_ONLY: no file changed and no reboot requested.')
        return
    if os.geteuid() != 0:
        raise SystemExit('Apply requires sudo; do not share your password with the assistant')
    if args.expected_sha256 != digest:
        raise SystemExit('Config changed or expected SHA256 omitted; rerun the review')
    if after == before:
        print('ALREADY_CONFIGURED: no change.')
        return
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = path.with_name('config.txt.cp21-backup-' + stamp)
    if backup.exists():
        raise SystemExit('Backup already exists; refusing to overwrite it')
    shutil.copy2(path, backup)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w', encoding='utf-8', dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(after)
            stream.flush()
            os.fsync(stream.fileno())
        shutil.copystat(path, temporary)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    print('BACKUP:', backup)
    print('APPLIED: reboot manually only after build/installation has finished.')


if __name__ == '__main__':
    main()
