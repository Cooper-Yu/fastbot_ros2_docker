"""Check missing and ambiguous device boundaries without opening serial ports."""

import pytest
from serial_motor.device_paths import LIDAR_USB_IDS, MOTOR_USB_IDS, resolve_serial_device


def adapter(tmp_path, name, identity, stable=None):
    """Create a tiny tty/sysfs fixture with a USB ancestor."""
    dev = tmp_path / 'dev'
    sys = tmp_path / 'sys'
    dev.mkdir(exist_ok=True)
    port = dev / name
    port.touch()
    usb = tmp_path / ('usb-' + name)
    usb.mkdir()
    (usb / 'idVendor').write_text(identity[0])
    (usb / 'idProduct').write_text(identity[1])
    (usb / 'interface').mkdir()
    (sys / name).mkdir(parents=True)
    (sys / name / 'device').symlink_to(usb / 'interface', target_is_directory=True)
    if stable:
        path = dev / 'serial/by-id' / stable
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(port)
    return dev, sys


def test_explicit_configuration_is_preserved(tmp_path):
    assert (
        resolve_serial_device('/chosen/path', 'lslidar', LIDAR_USB_IDS, tmp_path, tmp_path)
        == '/chosen/path'
    )


def test_alias_precedes_automatic_matching(tmp_path):
    dev, sys = adapter(tmp_path, 'ttyUSB0', ('1a86', '7523'))
    (dev / 'arduino_nano').symlink_to(dev / 'ttyUSB0')
    assert resolve_serial_device('', 'arduino_nano', MOTOR_USB_IDS, dev, sys) == str(
        dev / 'arduino_nano'
    )


def test_by_id_and_tty_names_do_not_count_twice(tmp_path):
    dev, sys = adapter(tmp_path, 'ttyACM0', ('1a86', '55d4'), 'unique-lidar')
    assert resolve_serial_device('', 'lslidar', LIDAR_USB_IDS, dev, sys) == str(
        dev / 'serial/by-id/unique-lidar'
    )


def test_course_cp2102_lidar_is_supported(tmp_path):
    dev, sys = adapter(tmp_path, 'ttyUSB1', ('10c4', 'ea60'))
    assert resolve_serial_device('', 'lslidar', LIDAR_USB_IDS, dev, sys) == str(dev / 'ttyUSB1')


def test_missing_device_is_not_guessed(tmp_path):
    with pytest.raises(ValueError, match='found 0'):
        resolve_serial_device('', 'lslidar', LIDAR_USB_IDS, tmp_path, tmp_path)


def test_two_candidates_require_an_explicit_choice(tmp_path):
    dev, sys = adapter(tmp_path, 'ttyUSB0', ('1a86', '7523'))
    adapter(tmp_path, 'ttyUSB1', ('0403', '6001'))
    with pytest.raises(ValueError, match='found 2'):
        resolve_serial_device('', 'arduino_nano', MOTOR_USB_IDS, dev, sys)


def test_nano_cannot_be_selected_as_lidar(tmp_path):
    dev, sys = adapter(tmp_path, 'ttyUSB0', ('1a86', '7523'))
    with pytest.raises(ValueError, match='found 0'):
        resolve_serial_device('', 'lslidar', LIDAR_USB_IDS, dev, sys)
