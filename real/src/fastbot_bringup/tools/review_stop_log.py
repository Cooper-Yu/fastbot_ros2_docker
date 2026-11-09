"""Review driver log evidence without opening ROS, serial ports, or hardware."""

import argparse
from dataclasses import dataclass
from decimal import Decimal
import json
from pathlib import Path
import re


@dataclass(frozen=True)
class Event:
    """One timestamped driver event; timestamps are logger times, not ACK times."""

    time: Decimal
    kind: str
    values: tuple[float, float] | None
    line: int


def parse_line(text, line):
    """Extract supported motor-driver events and ignore unrelated launch output."""
    if 'motor_driver' not in text:
        return None
    stamp = re.search(r'\[(\d+\.\d+)\]', text)
    if stamp is None:
        return None
    time = Decimal(stamp.group(1))
    command = re.search(r'Received linear.x=([^ ]+) m/s; angular.z=([^ ]+) rad/s', text)
    if command:
        values = tuple(float(value) for value in command.groups())
        kind = 'zero_request_received' if values == (0.0, 0.0) else 'motion_request_received'
        return Event(time, kind, values, line)
    if 'Timeout stop preview:' in text:
        return Event(time, 'timeout_zero_attempt_logged', None, line)
    if re.search(r"Motor command preview: 'm 0 0\\r'", text):
        return Event(time, 'command_zero_attempt_logged', None, line)
    velocity = re.search(r'Encoder angular speeds \(rad/s\): \(([^,]+), ([^)]+)\)', text)
    if velocity:
        return Event(
            time, 'wheel_interval_velocity', tuple(float(x) for x in velocity.groups()), line
        )
    if 'Motor communication failed' in text or 'Encoder read failed' in text:
        return Event(time, 'communication_fault', None, line)
    return None


def parse_events(text):
    """Reject clock reversals rather than silently joining incomparable intervals."""
    events = [
        event
        for index, line in enumerate(text.splitlines(), 1)
        if (event := parse_line(line, index)) is not None
    ]
    if any(right.time < left.time for left, right in zip(events, events[1:])):
        raise ValueError('Driver logger timestamps moved backwards; timing review is invalid')
    return events


def velocity_intervals(events):
    """Infer interval edges from adjacent velocity log times, not acquisition stamps."""
    samples = [event for event in events if event.kind == 'wheel_interval_velocity']
    return list(zip(samples, samples[1:]))


def longest_zero_run(intervals, epsilon):
    """Count consecutive near-zero feedback intervals without inventing missing data."""
    longest = current = 0
    for _, end in intervals:
        current = current + 1 if all(abs(value) <= epsilon for value in end.values) else 0
        longest = max(longest, current)
    return longest


def review_window(events, request, next_request, stable_samples, epsilon):
    """Separate zero attempts, mixed intervals, and later feedback evidence."""
    window = [
        event
        for event in events
        if event.time >= request.time and (next_request is None or event.time < next_request.time)
    ]
    attempts = [event for event in window if event.kind.endswith('zero_attempt_logged')]
    zero = attempts[0] if attempts else None
    result = {
        'request_line': request.line,
        'request_time': str(request.time),
        'linear': request.values[0],
        'angular': request.values[1],
        'serial_ack_time_available': False,
        'stable_samples_required': stable_samples,
    }
    if zero is None:
        result.update(assessment='NO_ZERO_ATTEMPT_LOGGED', longest_zero_feedback_run=0)
        return result
    intervals = [
        (start, end)
        for start, end in velocity_intervals(events)
        if end.time >= request.time and (next_request is None or end.time < next_request.time)
    ]
    complete_after = [(start, end) for start, end in intervals if start.time >= zero.time]
    mixed = [(start, end) for start, end in intervals if start.time < zero.time < end.time]
    stable_run = longest_zero_run(complete_after, epsilon)
    result.update(
        first_zero_attempt={
            'kind': zero.kind,
            'line': zero.line,
            'time': str(zero.time),
            'delay_from_driver_receipt_s': float(zero.time - request.time),
        },
        mixed_interval_lines=[end.line for _, end in mixed],
        complete_post_attempt_interval_count=len(complete_after),
        longest_zero_feedback_run=stable_run,
        communication_fault_logged=any(event.kind == 'communication_fault' for event in window),
        assessment=(
            'ZERO_FEEDBACK_RUN_OBSERVED'
            if stable_run >= stable_samples
            else 'AUTOMATED_SETTLE_NOT_PROVEN'
        ),
        feedback_intervals=[
            {
                'start_log_time': str(start.time),
                'end_log_time': str(end.time),
                'left_rad_s': end.values[0],
                'right_rad_s': end.values[1],
                'line': end.line,
                'relationship_to_first_zero_attempt': (
                    'complete_after'
                    if start.time >= zero.time
                    else 'crosses_attempt'
                    if start.time < zero.time < end.time
                    else 'before_attempt'
                ),
            }
            for start, end in intervals
        ],
    )
    return result


def review_text(text, stable_samples=5, epsilon=0.01):
    """Return evidence classifications, never a replacement for the original test verdict."""
    if stable_samples < 1 or epsilon < 0:
        raise ValueError('Require positive sample count and nonnegative velocity tolerance')
    events = parse_events(text)
    requests = [event for event in events if event.kind == 'motion_request_received']
    return {
        'clock': 'driver logger timestamps; not serial ACK or encoder acquisition timestamps',
        'interval_edges': 'inferred from consecutive velocity log times',
        'original_run_verdict_modified': False,
        'motions': [
            review_window(
                events,
                request,
                requests[index + 1] if index + 1 < len(requests) else None,
                stable_samples,
                epsilon,
            )
            for index, request in enumerate(requests)
        ],
    }


def markdown(report):
    """Render a compact evidence table while preserving uncertainty."""
    lines = [
        '# Stop-log review',
        '',
        'This offline review does not change the original integration verdict.',
        '',
        'Velocity interval edges use logger times as estimates. Serial ACK and exact',
        'sample-acquisition times are unavailable. A logged attempt is not a physical stop.',
        '',
        '| Motion | Linear / angular | First zero-attempt delay | Zero sample run | Evidence |',
        '| --- | --- | --- | --- | --- |',
    ]
    for index, item in enumerate(report['motions'], 1):
        delay = item.get('first_zero_attempt', {}).get('delay_from_driver_receipt_s')
        delay_text = f'{delay:.6f} s' if delay is not None else 'not logged'
        lines.append(
            f'| {index} | {item["linear"]:.6f} / {item["angular"]:.6f} | '
            f'{delay_text} | {item["longest_zero_feedback_run"]} | {item["assessment"]} |'
        )
    lines += [
        '',
        'Each window is classified only from its captured feedback.',
        'A mixed interval cannot establish motion exclusively after the zero attempt.',
        'Nonzero complete post-attempt intervals also prevent claiming an immediate stop.',
        'A separate human observation or later capture must remain separate evidence.',
    ]
    return '\n'.join(lines) + '\n'


def main():
    """Read one local log and write only the requested review artifacts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--json', dest='json_path', type=Path, required=True)
    parser.add_argument('--markdown', type=Path)
    args = parser.parse_args()
    report = review_text(args.log.read_text())
    args.json_path.write_text(json.dumps(report, indent=2) + '\n')
    if args.markdown:
        args.markdown.write_text(markdown(report))
    print(
        json.dumps(
            {
                'motions': len(report['motions']),
                'assessments': [item['assessment'] for item in report['motions']],
                'hardware_opened': False,
            }
        )
    )


if __name__ == '__main__':
    main()
