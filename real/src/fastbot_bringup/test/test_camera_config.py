"""Check boot-edit boundaries using strings, never the actual boot partition."""

import importlib.util
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[1] / 'tools/configure_legacy_camera.py'
spec = importlib.util.spec_from_file_location('cp21_camera_config', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_camera_plan_preserves_unrelated_settings():
    before = '[all]\nenable_uart=1\ncamera_auto_detect=1\ndisplay_auto_detect=1\n'
    after = module.desired_config(before)
    assert 'enable_uart=1\n' in after
    assert 'display_auto_detect=1\n' in after
    assert 'camera_auto_detect=0\n' in after
    assert after.endswith('start_x=1\n')


def test_existing_last_all_section_is_reused():
    after = module.desired_config('camera_auto_detect=1\n[all]\n')
    assert after.count('[all]') == 1


def test_plan_is_idempotent():
    after = module.desired_config('[all]\ncamera_auto_detect=1\n')
    assert module.desired_config(after) == after


@pytest.mark.parametrize(
    'before',
    [
        '[all]\n',
        'camera_auto_detect=1\ncamera_auto_detect=0\n',
        'camera_auto_detect=1\nstart_x=0\n',
    ],
)
def test_ambiguous_boot_configuration_is_rejected(before):
    with pytest.raises(ValueError):
        module.desired_config(before)
