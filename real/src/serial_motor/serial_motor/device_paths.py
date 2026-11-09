"""Resolve configured serial aliases or one identified USB adapter."""

from pathlib import Path

MOTOR_USB_IDS = {('1a86', '7523'), ('0403', '6001')}
LIDAR_USB_IDS = {('1a86', '55d4'), ('10c4', 'ea60')}


def _usb_identity(path, sys_root):
    """Read the nearest USB identity above a tty device, without opening it."""
    device = (sys_root / path.resolve().name / 'device').resolve()
    for parent in (device, *device.parents):
        try:
            return (
                (parent / 'idVendor').read_text().strip().lower(),
                (parent / 'idProduct').read_text().strip().lower(),
            )
        except OSError:
            continue
    return None


def resolve_serial_device(
    requested, alias, identities, dev_root=Path('/dev'), sys_root=Path('/sys/class/tty')
):
    """
    @brief Resolve one port without hardcoding a particular robot's serial number.

    @param[in] requested Explicit user override; returned unchanged when nonempty.
    @param[in] alias Trusted udev basename, such as arduino_nano or lslidar.
    @param[in] identities Supported USB vendor/product pairs for this device role.
    @param[in] dev_root Device directory; injectable for filesystem-only tests.
    @param[in] sys_root Tty sysfs directory; injectable for filesystem-only tests.
    @return The explicit path, existing udev alias or one unique matching port.
    @note No port is opened. Missing or ambiguous automatic matches raise ValueError.
    """
    if requested:
        return str(requested)
    named = dev_root / alias
    if named.exists():
        return str(named)
    paths = [
        *sorted((dev_root / 'serial/by-id').glob('*')),
        *sorted(dev_root.glob('ttyUSB*')),
        *sorted(dev_root.glob('ttyACM*')),
    ]
    matches = {}
    for path in paths:
        if path.exists() and _usb_identity(path, sys_root) in identities:
            matches.setdefault(path.resolve(), str(path))
    if len(matches) != 1:
        raise ValueError(
            f'Expected one {alias} USB device; found {len(matches)}. '
            'Set the port launch argument explicitly or configure its udev alias.'
        )
    return next(iter(matches.values()))
