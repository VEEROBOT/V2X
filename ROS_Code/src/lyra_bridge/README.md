# Lyra Bridge - ROS2 Package

**ROS2 bridge for Lyra STM32F405 motor controller**

Version: 1.0.0 (Phase 1 Complete)  
Compatible with: ROS2 Jazzy  
STM32 Firmware: v2.0+

---

## Overview

This package provides a complete ROS2 interface to the Lyra STM32-based motor controller, enabling:

- ✅ **Velocity control** via `/cmd_vel` (Twist messages)
- ✅ **Full telemetry** publishing (wheel speeds, encoders, IMU, battery)
- ✅ **Services** for ARM/DISARM/EMERGENCY_STOP
- ✅ **Auto-ARM** on command with safety timeout
- ✅ **Heartbeat monitoring** for connection health
- ✅ **Thread-safe** architecture with non-blocking UART

---

## Features

### Command & Control
- `/cmd_vel` subscriber with differential drive kinematics
- Auto-ARM on first command (configurable)
- Safety timeout: auto-stop after 500ms without commands
- Emergency stop service

### Telemetry Publishing
- `/wheel_rpm` - Wheel velocities (Float32MultiArray)
- `/wheel_ticks` - Encoder counts (Int32MultiArray)
- `/battery_voltage` - Battery voltage (Float32)
- `/imu/data_raw` - 6-axis IMU data (Imu message)
- `/lyra/armed` - Armed status (Bool)

### Services
- `/lyra/arm` - Enable motor control
- `/lyra/disarm` - Disable motors
- `/lyra/emergency_stop` - Immediate stop and disarm
- `/lyra/set_ros_mode` - Toggle ASCII telemetry

---

## Installation

### Prerequisites

```bash
# ROS2 Jazzy required
sudo apt update
sudo apt install ros-jazzy-desktop

# Python dependencies
pip3 install pyserial
```

### Build Package

```bash
# Create workspace (if not exists)
mkdir -p ~/lyra_ws/src
cd ~/lyra_ws/src

# Copy package here (lyra_bridge/)
cp -r /path/to/lyra_bridge .

# Build
cd ~/lyra_ws
colcon build --packages-select lyra_bridge

# Source workspace
source install/setup.bash
```

---

## Hardware Setup

### Wiring (RPi 5 ↔ STM32F405)

| STM32 Pin | Function | RPi Pin | GPIO |
|-----------|----------|---------|------|
| PC10 | UART3_TX | Pin 10 | GPIO15 (RXD) |
| PC11 | UART3_RX | Pin 8 | GPIO14 (TXD) |
| GND | Ground | Pin 6/9/14 | GND |

**Important:** Ensure common ground connection!

### UART Configuration (Raspberry Pi)

Check that GPIO UART is enabled:

```bash
# Verify UART device
ls -l /dev/ttyAMA0

# Should show: /dev/ttyAMA0 -> ...

# Check permissions (user should be in dialout group)
sudo usermod -aG dialout $USER
# Log out and back in for changes to take effect
```

---

## Quick Start

### 1. Launch Bridge

```bash
# Basic launch (default parameters)
ros2 launch lyra_bridge bridge.launch.py

# Custom serial port
ros2 launch lyra_bridge bridge.launch.py serial_port:=/dev/ttyUSB0

# Disable auto-ARM
ros2 launch lyra_bridge bridge.launch.py auto_arm:=false
```

### 2. Verify Connection

```bash
# Check topics
ros2 topic list
# Expected: /wheel_rpm, /wheel_ticks, /battery_voltage, /imu/data_raw

# Monitor telemetry
ros2 topic echo /wheel_rpm
ros2 topic hz /wheel_rpm  # Should be ~10Hz

# Check services
ros2 service list
# Expected: /robot/arm, /robot/disarm, /robot/emergency_stop
```

### 3. Test Manual Control

```bash
# Keyboard teleop (install if needed)
sudo apt install ros-jazzy-teleop-twist-keyboard

# Control robot
ros2 run teleop_twist_keyboard teleop_twist_keyboard \
  --ros-args --remap /cmd_vel:=/cmd_vel

# Robot should ARM automatically and respond to WASD keys
```

### 4. Service Control

```bash
# Manual ARM
ros2 service call /robot/arm std_srvs/srv/Trigger

# Disarm
ros2 service call /robot/disarm std_srvs/srv/Trigger

# Emergency stop
ros2 service call /robot/emergency_stop std_srvs/srv/Trigger
```

---

## Configuration

### Parameters File

Edit `config/lyra_params.yaml` to customize:

```yaml
lyra_bridge:
  ros__parameters:
    # Serial settings
    serial:
      port: /dev/ttyAMA0
      baudrate: 115200
    
    # Robot dimensions (CRITICAL - measure accurately!)
    robot:
      wheel_radius_m: 0.065      # Adjust for your wheels
      track_width_m: 0.377       # Measure wheel center to center
    
    # Safety
    control:
      cmd_vel_timeout_s: 0.5     # Increase for slower networks
      auto_arm: true             # Set false for manual arming
```

### Launch with Custom Config

```bash
ros2 launch lyra_bridge bridge.launch.py \
  params_file:=/path/to/custom_params.yaml
```

---

## Architecture

### Node Structure

```
┌─────────────────────────────────────────┐
│         LyraBridge Node                 │
│  ┌───────────────────────────────────┐  │
│  │   RX Thread (50Hz)                │  │
│  │   - Non-blocking UART read        │  │
│  │   - Packet parsing                │  │
│  │   - Telemetry publishing          │  │
│  └───────────────────────────────────┘  │
│                                          │
│  ┌───────────────────────────────────┐  │
│  │   Main Thread                     │  │
│  │   - /cmd_vel subscriber           │  │
│  │   - Services                      │  │
│  │   - Timers (telemetry, heartbeat) │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
         ↕ UART (115200 baud)
┌─────────────────────────────────────────┐
│         STM32F405 Controller            │
│   - Motor control (PID)                 │
│   - Encoder reading                     │
│   - IMU sampling                        │
│   - Binary protocol (Lyra)              │
└─────────────────────────────────────────┘
```

### Communication Flow

**Command Path:**
```
/cmd_vel → Twist to wheels → SET_WHEEL_VEL frame → UART → STM32 → Motors
```

**Telemetry Path:**
```
STM32 → GET_TELEMETRY response → UART → Parse → ROS topics
```

---

## Troubleshooting

### No Topics Publishing

**Check serial connection:**
```bash
# Monitor node logs
ros2 run lyra_bridge lyra_node

# Look for errors like:
# "STM32 not responding"
# "Serial not connected"
```

**Verify UART:**
```bash
# Test with minicom
sudo apt install minicom
minicom -D /dev/ttyAMA0 -b 115200

# Should see binary data if STM32 is transmitting
```

### Robot Not Moving

**Check armed status:**
```bash
ros2 topic echo /robot/armed

# If false and auto_arm=true, check:
# 1. Is cmd_vel being received?
ros2 topic echo /cmd_vel

# 2. Check node logs for ARM command
```

**Check wheel velocities:**
```bash
# Send command manually
ros2 topic pub /cmd_vel geometry_msgs/Twist \
  "{linear: {x: 0.2}, angular: {z: 0.0}}" -1

# Monitor wheel RPM
ros2 topic echo /wheel_rpm
# Should show non-zero values
```

### Connection Drops

**Check power:**
- Low battery can cause STM32 resets
- Monitor `/battery_voltage`

**Check USB power (if using USB-to-serial):**
- RPi USB may not provide enough current
- Use external power for STM32

**Check logs:**
```bash
ros2 run lyra_bridge lyra_node --ros-args --log-level debug
# Look for "Serial error, reconnecting..."
```

---

## Development

### Running Tests

```bash
cd ~/lyra_ws
colcon test --packages-select lyra_bridge
colcon test-result --verbose
```

### Code Style

```bash
# Python formatting
pip3 install black
black lyra_bridge/

# Linting
pip3 install flake8
flake8 lyra_bridge/
```

---

## Known Limitations

1. **No odometry publisher** - Coming in Phase 2
2. **No TF broadcaster** - Coming in Phase 2
3. **IMU orientation not computed** - Requires Madgwick filter (Phase 3)
4. **No dynamic PID tuning** - Can only set via services

---

## Roadmap

### Phase 1 (✅ Complete)
- Bidirectional control via `/cmd_vel`
- Full telemetry publishing
- Services for ARM/DISARM
- Safety timeout

### Phase 2 (Next)
- Odometry publisher (`/odom`)
- TF broadcaster
- URDF robot description

### Phase 3
- Sensor integration (LIDAR, camera)
- IMU orientation estimation

### Phase 4+
- SLAM and navigation
- Advanced features

---

## Support

For issues, questions, or contributions:
- **GitHub**: [Link to repository]
- **Email**: your.email@example.com
- **Documentation**: See main project README

---

## License

MIT License - See LICENSE file for details

---

## Acknowledgments

- STM32 firmware: Lyra Controller v2.0
- ROS2 integration: Phase 1 implementation
- Built with ROS2 Jazzy on Ubuntu 24.04
