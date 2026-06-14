"""
File: motor_test.py
Module: V2X Robot Platform — Motor Controller Integration Test

Purpose:
    Quick integration test script for the STM32 motor controller. Arms the
    robot, sends a forward velocity command, then disarms. Used to verify
    serial communication and motor response during hardware bring-up.

Author(s): Praveen Kumar
Company: Siliris Technologies Pvt. Ltd
Created: 1st March 2026
Version: 1.0

License:
    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
    Proprietary - See LICENSE file for terms and conditions.
"""
from robot_driver import RobotDriver
import time

print("Creating driver...")
d = RobotDriver(port="/dev/ttyAMA0", baudrate=115200)

print("Starting driver...")
d.start()

time.sleep(2)

print("Sending ARM...")
d.arm()

time.sleep(1)

print("Driving forward...")

for _ in range(30):   # 3 seconds
    d.set_velocity(0.10, 0.0)
    time.sleep(0.1)

print("Stopping...")
d.set_velocity(0.0, 0.0)

time.sleep(1)

print("Disarming...")
d.disarm()

time.sleep(1)

d.stop()

print("Done")
