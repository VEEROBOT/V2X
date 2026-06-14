#!/usr/bin/env python3
"""
File: diag_drive.py
Module: V2X Robot Platform — Diagnostic Drive Tool

Purpose:
    Diagnostic tool for manual driving with live telemetry printout. Reads
    joystick input and drives the robot while displaying armed state, stall
    flags, wheel RPM, and command age — useful for diagnosing stutter and
    motor controller behaviour without running the full autonomy stack.

Author(s): Praveen Kumar
Company: Siliris Technologies Pvt. Ltd
Created: 1st March 2026
Version: 1.0

Usage:
    python3 diag_drive.py
    Hold LB to drive. Ctrl-C to stop.

License:
    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
    Proprietary - See LICENSE file for terms and conditions.
"""
import os, sys, time, threading, logging
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

logging.basicConfig(level=logging.WARNING)  # suppress driver noise

from robot_driver import RobotDriver
from lib.telemetry import parse_status_flags

import pygame
pygame.init()
pygame.joystick.init()

if pygame.joystick.get_count() == 0:
    print("No joystick found"); sys.exit(1)

js = pygame.joystick.Joystick(0)
js.init()
print(f"Joystick: {js.get_name()}")
print("Hold LB (btn 4) to drive. Ctrl-C to quit.")
print()
print(f"{'Time':>7}  {'Armed':>5}  {'Stall':>5}  {'vx':>5}  {'wz':>5}  {'RPM FL':>7}  {'RPM BL':>7}  {'RPM BR':>7}  {'RPM FR':>7}  {'Cmd':>6}")
print("-" * 85)

driver = RobotDriver(port='/dev/ttyAMA0', baudrate=115200)
driver.start()
time.sleep(1.0)
driver.arm()

t0 = time.monotonic()
last_cmd_time = None

try:
    while True:
        pygame.event.pump()

        deadman = bool(js.get_button(4))
        turbo   = bool(js.get_button(5))

        raw_thr = js.get_axis(1) if js.get_numaxes() > 1 else 0.0
        raw_str = js.get_axis(3) if js.get_numaxes() > 3 else 0.0
        if abs(raw_thr) < 0.10: raw_thr = 0.0
        if abs(raw_str) < 0.10: raw_str = 0.0

        if deadman:
            speed = 0.80 if turbo else 0.40
            vx = -raw_thr * speed
            wz = -raw_str * 1.5
            driver.set_velocity(vx, wz)
            last_cmd_time = time.monotonic()
        else:
            driver.set_velocity(0.0, 0.0)
            vx, wz = 0.0, 0.0

        t   = telem = driver.get_telemetry()
        now = time.monotonic() - t0

        if telem:
            flags  = parse_status_flags(telem['status_flags'])
            stalls = [flags[f'motor{i}_stall'] for i in range(1, 5)]
            stall_str = ''.join(str(i+1) for i, s in enumerate(stalls) if s) or '-'
            rpms = telem['wheel_rpm']
            print(f"{now:7.1f}  {'Y' if flags['armed'] else 'N':>5}  {stall_str:>5}  "
                  f"{vx:+5.2f}  {wz:+5.2f}  "
                  f"{rpms[0]:7.1f}  {rpms[1]:7.1f}  {rpms[2]:7.1f}  {rpms[3]:7.1f}  "
                  f"{'DRIVE' if deadman else 'STOP':>6}",
                  flush=True)

        time.sleep(0.1)

except KeyboardInterrupt:
    print("\nShutting down...")
finally:
    driver.set_velocity(0.0, 0.0)
    time.sleep(0.2)
    driver.disarm()
    driver.stop()
