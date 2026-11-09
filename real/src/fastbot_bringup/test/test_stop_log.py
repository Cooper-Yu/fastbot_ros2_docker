"""Check that incomplete log evidence never becomes a fabricated stop PASS."""

import importlib.util
from pathlib import Path
import sys

import pytest

path = Path(__file__).resolve().parents[1] / 'tools/review_stop_log.py'
spec = importlib.util.spec_from_file_location('cp21_stop_log', path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def log_line(stamp, message):
    return f'[motor_driver-1] [INFO] [{stamp}] [fastbot.motor_driver]: {message}'


def request(stamp='10.000', linear='0.03', angular='0.0'):
    return log_line(stamp, f'Received linear.x={linear} m/s; angular.z={angular} rad/s')


def speed(stamp, left, right):
    return log_line(stamp, f'Encoder angular speeds (rad/s): ({left}, {right})')


def test_timeout_attempt_is_not_ack_or_physical_stop():
    text = '\n'.join([request(), log_line('10.556', "Timeout stop preview: 'm 0 0\\r'")])
    motion = module.review_text(text)['motions'][0]
    assert motion['first_zero_attempt']['delay_from_driver_receipt_s'] == 0.556
    assert motion['serial_ack_time_available'] is False
    assert motion['assessment'] == 'AUTOMATED_SETTLE_NOT_PROVEN'


def test_mixed_nonzero_interval_does_not_prove_motion_only_after_zero():
    text = '\n'.join(
        [
            request(),
            speed('10.49', 1, -1),
            log_line('10.55', "Timeout stop preview: 'm 0 0\\r'"),
            speed('10.59', 0.15, -0.52),
        ]
    )
    motion = module.review_text(text)['motions'][0]
    assert len(motion['mixed_interval_lines']) == 1
    assert motion['complete_post_attempt_interval_count'] == 0
    assert motion['assessment'] == 'AUTOMATED_SETTLE_NOT_PROVEN'


def test_full_post_attempt_nonzero_interval_cannot_be_declared_stopped():
    text = '\n'.join(
        [
            request(),
            speed('10.49', 1, -1),
            log_line('10.55', "Timeout stop preview: 'm 0 0\\r'"),
            speed('10.59', 0.15, -0.52),
            speed('10.69', 0.025, 0.05),
        ]
    )
    motion = module.review_text(text)['motions'][0]
    assert motion['complete_post_attempt_interval_count'] == 1
    assert motion['longest_zero_feedback_run'] == 0
    assert motion['assessment'] == 'AUTOMATED_SETTLE_NOT_PROVEN'


def test_five_complete_zero_intervals_are_feedback_evidence_only():
    lines = [request(), log_line('10.5', "Timeout stop preview: 'm 0 0\\r'"), speed('10.6', 0, 0)]
    lines += [speed(f'10.{number}', 0, 0) for number in (70, 75, 80, 85, 90)]
    result = module.review_text('\n'.join(lines))
    assert result['motions'][0]['assessment'] == 'ZERO_FEEDBACK_RUN_OBSERVED'
    assert result['motions'][0]['longest_zero_feedback_run'] == 5
    assert result['original_run_verdict_modified'] is False


def test_zero_history_before_a_new_command_cannot_satisfy_that_commands_stop():
    lines = [request(), log_line('10.1', "Timeout stop preview: 'm 0 0\\r'")]
    lines += [speed(f'10.{number}', 0, 0) for number in (20, 30, 40, 50, 60, 70)]
    lines += [request('11.0', '0', '-0.59')]
    report = module.review_text('\n'.join(lines))
    assert report['motions'][0]['assessment'] == 'ZERO_FEEDBACK_RUN_OBSERVED'
    assert report['motions'][1]['assessment'] == 'NO_ZERO_ATTEMPT_LOGGED'


def test_zero_request_receipt_is_not_serial_zero_attempt():
    text = '\n'.join([request(), request('10.4', '0.0', '0.0')])
    assert module.review_text(text)['motions'][0]['assessment'] == 'NO_ZERO_ATTEMPT_LOGGED'


def test_communication_failure_is_preserved():
    text = '\n'.join(
        [
            request(),
            log_line('10.5', "Timeout stop preview: 'm 0 0\\r'"),
            log_line('10.6', 'Motor communication failed; unconfirmed: timeout'),
        ]
    )
    assert module.review_text(text)['motions'][0]['communication_fault_logged'] is True


def test_driver_clock_reversal_is_rejected():
    with pytest.raises(ValueError, match='timestamps moved backwards'):
        module.review_text('\n'.join([request('10.5'), speed('10.4', 0, 0)]))
