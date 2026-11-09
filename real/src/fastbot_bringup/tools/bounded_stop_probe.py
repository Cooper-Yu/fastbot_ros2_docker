"""One-shot, opt-in motor stop probe; fake serial transport is the default."""

import argparse
import json
import signal
import time
from pathlib import Path

import rclpy
from geometry_msgs.msg import Twist
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from serial_motor import motor_driver as driver_module


class FakeTransport:
    """Emulate command ACKs and cumulative counts without opening any device."""

    def __init__(self, late_zero=False):
        self.targets = (0, 0)
        self.counts = [0.0, 0.0]
        self.last_time = time.monotonic()
        self.reply = b''
        self.late_zero = late_zero
        self.pending_zero = None
        self.closed = False

    def advance(self):
        now = time.monotonic()
        end = min(now, self.pending_zero) if self.pending_zero else now
        for index in (0, 1):
            self.counts[index] += self.targets[index] * 30 * max(0, end - self.last_time)
        if self.pending_zero and now >= self.pending_zero:
            self.targets = (0, 0)
            self.pending_zero = None
        self.last_time = now

    def write(self, payload):
        self.advance()
        fields = payload.decode().strip().split()
        if fields[0] == 'm':
            targets = tuple(int(value) for value in fields[1:])
            if self.late_zero and targets == (0, 0) and self.targets != (0, 0):
                self.pending_zero = self.pending_zero or time.monotonic() + 0.3
            else:
                self.targets = targets
            self.reply = b'OK\r\n'
        elif fields[0] == 'e':
            self.reply = f'{int(self.counts[0])} {int(self.counts[1])}\r\n'.encode()
        else:
            raise AssertionError('Unexpected fake transaction')
        return len(payload)

    def readline(self):
        return self.reply

    def close(self):
        self.closed = True


class TracedDriver(driver_module.MotorDriver):
    """Observe the original driver on one monotonic clock without changing its timers."""

    def __init__(self, events):
        self.events = events
        super().__init__()

    def event(self, kind, **fields):
        event = {'kind': kind, 'time': time.monotonic(), **fields}
        self.events.append(event)
        return event

    def cmd_vel_callback(self, message):
        self.event('request', linear=message.linear.x, angular=message.angular.z)
        super().cmd_vel_callback(message)

    def send_command_safely(self, command):
        self.event('send_begin', command=command)
        result = super().send_command_safely(command)
        self.event('send_return', command=command, acknowledged=bool(result and self.connection))
        return result

    def update_encoder_speed_sample(self, left, right, sample_time):
        previous = self.previous_encoder_sample
        speeds = super().update_encoder_speed_sample(left, right, sample_time)
        self.event(
            'sample',
            acquired=sample_time,
            interval_start=previous[2] if previous else None,
            counts=[left, right],
            speeds=speeds,
        )
        return speeds


def post_zero_tail(events, zero_time):
    """Return only consecutive near-zero samples with identical cumulative counts."""
    tail = []
    for event in events:
        if event['kind'] != 'sample' or event['interval_start'] is None:
            continue
        if event['interval_start'] < zero_time:
            continue
        if all(abs(value) < 0.01 for value in event['speeds']):
            if tail and event['counts'] != tail[-1]['counts']:
                tail = []
            tail.append(event)
        else:
            tail = []
    return tail


def stop_zero(publisher):
    """Request zero through the only ROS command source."""
    publisher.publish(Twist())


def run_trial(executor, driver, observer, publisher, events, report):
    """Send exactly one right-turn input, retain the guard, and collect a zero-only tail."""
    ready_deadline = time.monotonic() + 5
    while time.monotonic() < ready_deadline:
        executor.spin_once(timeout_sec=0.02)
        samples = [item for item in events if item['kind'] == 'sample']
        if len(samples) >= 6 and observer.count_subscribers('/fastbot/cmd_vel') == 1:
            assert driver.count_publishers('/fastbot/cmd_vel') == 1, 'Other command publisher'
            assert len(post_zero_tail(events, 0)) >= 5, 'Initial feedback is not stationary'
            break
    else:
        raise RuntimeError('No stationary feedback or ROS discovery before readiness deadline')

    command = Twist()
    command.angular.z = -0.59049
    publisher.publish(command)
    report['nonzero_published'] = 1
    until = time.monotonic() + 3
    request = None
    zero_ack = None
    guard_checked = False
    guard_failed = False
    while time.monotonic() < until:
        executor.spin_once(timeout_sec=0.01)
        assert not driver.communication_fault, 'Driver communication fault; stop unconfirmed'
        requests = [item for item in events if item['kind'] == 'request' and item['angular'] != 0]
        if not requests:
            continue
        assert len(requests) == 1, 'More than one nonzero command received'
        request = requests[0]
        now = time.monotonic()
        samples = [item for item in events if item['kind'] == 'sample']
        assert now - samples[-1]['acquired'] < 0.3, 'Feedback lost'
        acknowledgments = [
            item
            for item in events
            if item['kind'] == 'send_return'
            and item['time'] >= request['time']
            and item['command'] == 'm 0 0\r'
            and item['acknowledged']
        ]
        zero_ack = acknowledgments[0] if acknowledgments else None
        if now - request['time'] >= 0.7 and not guard_checked:
            guard_checked = True
            guard_failed = zero_ack is None or any(abs(x) >= 0.01 for x in samples[-1]['speeds'])
            report['guard'] = {
                'failed': guard_failed,
                'checked_at': now,
                'latest_sample_time': samples[-1]['acquired'],
                'latest_speeds': samples[-1]['speeds'],
            }
            stop_zero(publisher)
        if zero_ack and guard_checked and len(post_zero_tail(events, zero_ack['time'])) >= 5:
            report['status'] = 'FAIL_PROTECTION' if guard_failed else 'PASS'
            report['zero_ack_delay_s'] = zero_ack['time'] - request['time']
            report['settled_tail_samples'] = len(post_zero_tail(events, zero_ack['time']))
            tail = post_zero_tail(events, zero_ack['time'])
            report['stable_interval_start_delay_s'] = tail[0]['interval_start'] - request['time']
            report['stable_run_confirmed_delay_s'] = tail[4]['acquired'] - request['time']
            motion = [
                item
                for item in samples
                if item['acquired'] >= request['time'] and item['speeds'] is not None
            ]
            report['right_turn_signs_seen'] = any(
                item['speeds'][0] > 0.01 and item['speeds'][1] < -0.01 for item in motion
            )
            assert report['right_turn_signs_seen'], 'Requested right-turn feedback absent'
            return
        if now - request['time'] >= 2:
            raise RuntimeError('No stable stop tail within 2 s; no further motion permitted')
    raise RuntimeError('No received command within overall trial budget')


def main():
    """Own the connection and always attempt zero before closing it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hardware', action='store_true', help='Requires current onsite approval')
    parser.add_argument(
        '--late-zero', action='store_true', help='Fake-only protective-failure case'
    )
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert not (args.hardware and args.late_zero), 'Late-zero emulation is fake-only'
    events = []
    report = {
        'hardware': args.hardware,
        'status': 'ERROR',
        'nonzero_published': 0,
        'scope': 'isolated local one-shot timeout probe, not formal launch/cloud acceptance',
        'clock': 'same-process host monotonic; ACK is not a physical stop',
        'events': events,
    }
    driver = observer = executor = connection = None
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    rclpy.init(
        args=[
            '--ros-args',
            '-p',
            'wheel_separation:=0.12',
            '-p',
            'wheel_radius:=0.032',
            '-p',
            'encoder_cpr:=2537',
            '-p',
            'loop_rate:=30',
        ]
    )
    try:
        driver = TracedDriver(events)
        if args.hardware:
            port = driver_module.resolve_serial_device(
                '', 'arduino_nano', driver_module.MOTOR_USB_IDS
            )
            report['port'] = port
            connection = driver_module.prepare_serial_connection(
                driver_module.serial.Serial, port, 57600, 0.2, 0.2
            )
            driver_module.open_prepared_connection(connection)
            driver_module.check_controller_ready(connection, 57600)
        else:
            connection = FakeTransport(args.late_zero)
        driver.connection = connection
        observer = Node('cp21_stop_observer')
        publisher = observer.create_publisher(Twist, '/fastbot/cmd_vel', 10)
        executor = SingleThreadedExecutor()
        executor.add_node(driver)
        executor.add_node(observer)
        run_trial(executor, driver, observer, publisher, events, report)
    except (Exception, KeyboardInterrupt) as error:
        report.update(status='ERROR', error=str(error) or type(error).__name__)
    finally:
        if driver and connection:
            report['cleanup_zero_acknowledged'] = driver.send_command_safely('m 0 0\r')
            if not report['cleanup_zero_acknowledged']:
                report['status'] = 'ERROR_STOP_UNCONFIRMED'
        if executor:
            executor.shutdown()
        for node in (observer, driver):
            if node:
                node.destroy_node()
        if connection:
            connection.close()
            report['connection_closed'] = True
        rclpy.shutdown()
        args.output.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({key: value for key, value in report.items() if key != 'events'}))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
