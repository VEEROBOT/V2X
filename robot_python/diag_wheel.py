#!/usr/bin/env python3
"""
Wheel diagnostic — tests each wheel individually at slow speed and
prints RPM + tick direction from telemetry.

Usage:
    cd ~/projects/V2X/robot_python
    source .venv/bin/activate
    python diag_wheel.py

Wheel index order (matches telemetry):  [0=FL, 1=BL, 2=BR, 3=FR]
"""
import time
import sys
from robot_driver import RobotDriver
from lib.protocol import build_arm_command, build_disarm_command, build_set_wheel_vel_command
from lib.telemetry import parse_telemetry, parse_status_flags

WHEEL_NAMES = ['FL', 'BL', 'BR', 'FR']
TEST_SPEED   = 5.0    # rad/s — slow enough to be safe, fast enough to read clearly
TEST_SECS    = 2.0    # how long to spin each wheel
PORT         = '/dev/ttyAMA0'
BAUD         = 115200


def main():
    d = RobotDriver(port=PORT, baudrate=BAUD)
    d.start()
    time.sleep(1.5)
    d.arm()
    time.sleep(0.5)

    print(f"\n{'Wheel':<6} {'Cmd rad/s':>10} {'Actual RPM':>12} {'Tick delta':>12}  {'Direction'}")
    print('-' * 60)

    for idx in range(4):
        # Zero all wheels, then spin only this one
        vels = [0.0] * 4
        vels[idx] = TEST_SPEED

        # Grab a baseline tick count before starting
        telem_before = None
        for _ in range(5):
            t = d.get_telemetry()
            if t:
                telem_before = t
                break
            time.sleep(0.1)

        # Send command for TEST_SECS
        t_end = time.monotonic() + TEST_SECS
        while time.monotonic() < t_end:
            d._send(build_set_wheel_vel_command(d._next_seq(), vels))
            time.sleep(0.05)

        # Read telemetry right after
        telem_after = None
        for _ in range(10):
            t = d.get_telemetry()
            if t:
                telem_after = t
                break
            time.sleep(0.05)

        # Stop
        d._send(build_set_wheel_vel_command(d._next_seq(), [0.0] * 4))
        time.sleep(0.3)

        if telem_before and telem_after:
            rpm   = telem_after['wheel_rpm'][idx]
            delta = telem_after['wheel_ticks'][idx] - telem_before['wheel_ticks'][idx]
            direction = 'OK (+)' if delta > 0 else ('REVERSED (-)' if delta < 0 else 'NO MOVEMENT')
            print(f"{WHEEL_NAMES[idx]:<6} {TEST_SPEED:>10.1f} {rpm:>12.1f} {delta:>12}  {direction}")
        else:
            print(f"{WHEEL_NAMES[idx]:<6} {TEST_SPEED:>10.1f}  {'NO TELEMETRY':>24}")

    # All stop
    d._send(build_set_wheel_vel_command(d._next_seq(), [0.0] * 4))
    time.sleep(0.5)
    d.disarm()
    time.sleep(0.5)
    d.stop()

    print('\nExpected: all tick deltas positive (same sign as command).')
    print('If FR (idx 3) shows REVERSED or very large RPM, encoder is flipped.')


if __name__ == '__main__':
    main()
