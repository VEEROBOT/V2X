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
