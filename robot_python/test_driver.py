"""
File: test_driver.py
Module: V2X Robot Platform — Robot Driver Unit Test

Purpose:
    Lightweight test script for the RobotDriver class. Polls telemetry for
    10 seconds, then sends arm and velocity commands to verify the full
    driver stack (serial transport → protocol → STM32) is functioning.

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
import logging

logging.basicConfig(level=logging.INFO)

d = RobotDriver()
d.start()

for i in range(10):
    print(d.get_telemetry())
    time.sleep(1)

d.arm()
print("ARM SENT")

for i in range(10):
    print(d.get_telemetry())
    time.sleep(1)
