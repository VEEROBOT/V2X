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
