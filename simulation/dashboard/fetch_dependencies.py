"""Coach build support: parallel downloads from the signed APT dependency plan."""

import concurrent.futures
import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
import urllib.request

plan = subprocess.check_output(
    [
        'apt-get',
        '-o',
        'Acquire::ForceHash=SHA256',
        '--print-uris',
        '--yes',
        '--download-only',
        '--no-install-recommends',
        'install',
        *sys.argv[1:],
    ],
    text=True,
)
items = []
cache = Path('/var/cache/apt/archives')
cache.mkdir(parents=True, exist_ok=True)
for line in plan.splitlines():
    if not line.startswith("'"):
        continue
    url, filename, size, digest = shlex.split(line)
    if Path(filename).name != filename or not filename.endswith('.deb'):
        raise ValueError('Invalid archive filename')
    if not digest.startswith('SHA256:'):
        raise ValueError('Expected APT SHA256 digest')
    items.append((url, filename, int(size), digest.split(':', 1)[1]))


def fetch(item):
    url, filename, size, expected = item
    target = cache / filename

    def valid(path):
        return (
            path.is_file()
            and path.stat().st_size == size
            and hashlib.sha256(path.read_bytes()).hexdigest() == expected
        )

    if valid(target):
        return 'cached'
    temporary = cache / (filename + '.cp23-part')
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'CP23-APT-download/1.0'})
            digest = hashlib.sha256()
            length = 0
            with (
                urllib.request.urlopen(request, timeout=60) as response,
                temporary.open('wb') as output,
            ):
                while chunk := response.read(262144):
                    length += len(chunk)
                    if length > size:
                        raise ValueError('APT archive exceeds signed size')
                    digest.update(chunk)
                    output.write(chunk)
            if length != size or digest.hexdigest() != expected:
                raise ValueError('APT archive size/SHA256 mismatch')
            os.replace(temporary, target)
            return 'downloaded'
        except Exception:
            temporary.unlink(missing_ok=True)
            if attempt == 3:
                raise
            time.sleep(attempt + 1)


print('APT signed plan:', len(items), 'archives;', sum(i[2] for i in items), 'bytes', flush=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
    results = list(executor.map(fetch, items))
print(
    'APT SHA256 verified:', len(results), 'archives;', results.count('cached'), 'cached', flush=True
)
