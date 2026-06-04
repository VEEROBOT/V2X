# Lyra Bridge - Testing & Validation Guide

**Phase 1 Validation Checklist**

---

## 🎯 Testing Objectives

1. ✅ Verify serial communication (STM32 ↔ RPi)
2. ✅ Confirm telemetry publishing at correct rates
3. ✅ Validate `/cmd_vel` → wheel velocity conversion
4. ✅ Test safety timeout and auto-disarm
5. ✅ Verify services (ARM/DISARM/EMERGENCY_STOP)
6. ✅ Check connection resilience (auto-reconnect)

---

## 📋 Pre-Test Checklist

### Hardware
- [ ] STM32 powered and firmware v2.0 running
- [ ] UART3 connected: STM32 PC10→RPi GPIO15, PC11→GPIO14
- [ ] Common ground connected
- [ ] Battery charged (>11V)
- [ ] Motors can move safely (no obstructions)

### Software
- [ ] ROS2 Jazzy installed
- [ ] lyra_bridge package built successfully
- [ ] Serial permissions: user in `dialout` group
- [ ] `/dev/ttyAMA0` accessible

---

## 🧪 Test Suite

### Test 1: Basic Connection ✅

**Objective:** Verify serial communication established

```bash
# Terminal 1: Launch bridge
ros2 launch lyra_bridge bridge.launch.py

# Terminal 2: Check topics
ros2 topic list

# Expected output:
/battery_voltage
/imu/data_raw
/parameter_events
/robot/armed
/rosout
/wheel_rpm
/wheel_ticks
```

**Success Criteria:**
- ✅ Node starts without errors
- ✅ All 6 topics visible
- ✅ No "serial not connected" warnings

---

### Test 2: Telemetry Rate ✅

**Objective:** Confirm telemetry publishing at 10Hz

```bash
# Check wheel RPM rate
ros2 topic hz /wheel_rpm

# Expected: ~10 Hz

# Check IMU rate
ros2 topic hz /imu/data_raw

# Expected: ~10 Hz
```

**Success Criteria:**
- ✅ `/wheel_rpm` at 9-11 Hz
- ✅ `/imu/data_raw` at 9-11 Hz
- ✅ No significant jitter (std dev < 1 Hz)

---

### Test 3: Telemetry Content ✅

**Objective:** Verify telemetry data is valid

```bash
# Check wheel RPM (should be ~0 when stationary)
ros2 topic echo /wheel_rpm --once

# Expected:
# data: [0.0, 0.0, 0.0, 0.0] (or small values)

# Check battery voltage
ros2 topic echo /battery_voltage --once

# Expected: 11.0 - 12.6 V (for 3S LiPo)

# Check IMU
ros2 topic echo /imu/data_raw --once

# Expected:
# linear_acceleration.z ≈ 9.8 m/s² (gravity)
# angular_velocity.* ≈ 0 (stationary)
```

**Success Criteria:**
- ✅ Battery voltage in valid range
- ✅ IMU Z-accel near 9.8 m/s²
- ✅ Wheel RPM near zero when stationary

---

### Test 4: Manual Wheel Rotation ✅

**Objective:** Verify encoder feedback

```bash
# Terminal 1: Monitor wheel ticks
ros2 topic echo /wheel_ticks

# Manually rotate front-left wheel forward
# Observe tick count changes

# Rotate backward
# Observe tick count decreases
```

**Success Criteria:**
- ✅ Tick counts increase when wheel rotates forward
- ✅ Tick counts decrease when wheel rotates backward
- ✅ All 4 wheels report correct direction

---

### Test 5: ARM/DISARM Services ✅

**Objective:** Test manual control services

```bash
# ARM robot
ros2 service call /robot/arm std_srvs/srv/Trigger

# Expected response:
# success: True
# message: 'ARM command sent'

# Check armed status
ros2 topic echo /robot/armed --once

# Expected: data: true

# DISARM robot
ros2 service call /robot/disarm std_srvs/srv/Trigger

# Check armed status again
ros2 topic echo /robot/armed --once

# Expected: data: false
```

**Success Criteria:**
- ✅ ARM service returns success
- ✅ Armed status changes to true
- ✅ DISARM service returns success
- ✅ Armed status changes to false

---

### Test 6: Emergency Stop ✅

**Objective:** Verify emergency stop works

```bash
# ARM robot first
ros2 service call /robot/arm std_srvs/srv/Trigger

# Send emergency stop
ros2 service call /robot/emergency_stop std_srvs/srv/Trigger

# Check armed status
ros2 topic echo /robot/armed --once

# Expected: data: false (disarmed immediately)
```

**Success Criteria:**
- ✅ Emergency stop returns success
- ✅ Robot disarms immediately
- ✅ All motors stop

---

### Test 7: Simple Forward Motion ⚡ CRITICAL

**Objective:** Verify /cmd_vel → motor control

**⚠️ SAFETY:** Ensure robot can move safely (no obstacles, on ground/test stand)

```bash
# Terminal 1: Monitor wheel RPM
ros2 topic echo /wheel_rpm

# Terminal 2: Send forward command
ros2 topic pub /cmd_vel geometry_msgs/Twist \
  "{linear: {x: 0.2}, angular: {z: 0.0}}" -r 10

# Observe:
# 1. Robot should auto-ARM (if auto_arm=true)
# 2. All wheels should report positive RPM
# 3. Robot should move forward slowly

# Stop (Ctrl+C in Terminal 2)
# Robot should stop after 500ms timeout
```

**Success Criteria:**
- ✅ Robot auto-arms on first command
- ✅ All 4 wheels show positive RPM (~20-30 RPM for 0.2 m/s)
- ✅ Robot moves forward smoothly
- ✅ Robot stops after timeout when command stops

**Expected Wheel Speeds:**
```
v = 0.2 m/s, wheel_radius = 0.065m
ω = v / r = 0.2 / 0.065 = 3.08 rad/s
RPM = (3.08 * 60) / (2π) ≈ 29.4 RPM

All wheels: ~29 RPM (small variation is normal)
```

---

### Test 8: Rotation in Place ✅

**Objective:** Test angular velocity control

```bash
# Send rotation command (CCW)
ros2 topic pub /cmd_vel geometry_msgs/Twist \
  "{linear: {x: 0.0}, angular: {z: 0.5}}" -r 10

# Monitor wheel RPM
ros2 topic echo /wheel_rpm

# Expected:
# Left wheels (FL, RL): negative RPM
# Right wheels (FR, RR): positive RPM
# Magnitude should be equal
```

**Success Criteria:**
- ✅ Left wheels rotate backward (negative RPM)
- ✅ Right wheels rotate forward (positive RPM)
- ✅ Robot rotates CCW (counter-clockwise)
- ✅ Magnitude approximately equal

**Expected Wheel Speeds:**
```
ω = 0.5 rad/s, track_width = 0.377m
v_left = -ω * (track/2) = -0.5 * 0.1475 = -0.074 m/s
v_right = +0.5 * 0.1475 = +0.074 m/s

Left wheels: ≈ -11 RPM
Right wheels: ≈ +11 RPM
```

---

### Test 9: Safety Timeout ⚠️ CRITICAL

**Objective:** Verify auto-stop on timeout

```bash
# Send continuous command
ros2 topic pub /cmd_vel geometry_msgs/Twist \
  "{linear: {x: 0.3}, angular: {z: 0.0}}" -r 10

# Wait for robot to move
# Ctrl+C to stop publishing

# Monitor wheel RPM
ros2 topic echo /wheel_rpm

# Expected:
# - RPM continues for ~500ms after Ctrl+C
# - Then drops to 0
# - Robot disarms automatically (if auto_arm=true)
```

**Success Criteria:**
- ✅ Robot continues moving briefly after command stops
- ✅ Robot stops within 1 second
- ✅ All wheels report 0 RPM
- ✅ Robot auto-disarms (check `/robot/armed`)

---

### Test 10: Keyboard Teleop ✅

**Objective:** Full manual control test

```bash
# Install teleop keyboard
sudo apt install ros-jazzy-teleop-twist-keyboard

# Run teleop
ros2 run teleop_twist_keyboard teleop_twist_keyboard

# Test all directions:
# - W: Forward
# - S: Backward
# - A: Rotate CCW
# - D: Rotate CW
# - Q/E: Forward + rotation
# - X: Stop
# - Space: Emergency stop
```

**Success Criteria:**
- ✅ All directions work smoothly
- ✅ Speed increases with multiple keypresses
- ✅ Emergency stop (Space) works immediately
- ✅ Timeout works when keys released

---

### Test 11: Connection Resilience ✅

**Objective:** Test auto-reconnect

```bash
# Terminal 1: Launch bridge
ros2 launch lyra_bridge bridge.launch.py

# Terminal 2: Monitor connection
ros2 topic hz /wheel_rpm

# Disconnect USB (if using USB-to-serial)
# OR unplug/replug STM32 power

# Observe logs:
# "Serial error, reconnecting..."

# Wait ~2 seconds
# Connection should restore
# Telemetry should resume
```

**Success Criteria:**
- ✅ Node detects disconnect
- ✅ Auto-reconnect attempts (every 2s)
- ✅ Telemetry resumes when reconnected
- ✅ No need to restart node

---

### Test 12: Stress Test (Optional) 🔥

**Objective:** Continuous operation test

```bash
# Run for 10 minutes with random motion
ros2 run lyra_bridge stress_test.py  # (create simple random cmd_vel script)

# Monitor:
# - Packet loss
# - Memory usage
# - CPU usage
# - Temperature (if sensors available)
```

**Success Criteria:**
- ✅ No packet loss over 10 min
- ✅ Constant telemetry rate
- ✅ No memory leaks (stable RSS)

---

## 📊 Validation Checklist

After completing all tests, verify:

- [ ] **Test 1:** Connection established ✅
- [ ] **Test 2:** Telemetry rate correct ✅
- [ ] **Test 3:** Telemetry content valid ✅
- [ ] **Test 4:** Encoders working ✅
- [ ] **Test 5:** ARM/DISARM services ✅
- [ ] **Test 6:** Emergency stop ✅
- [ ] **Test 7:** Forward motion ✅ (CRITICAL)
- [ ] **Test 8:** Rotation ✅
- [ ] **Test 9:** Safety timeout ✅ (CRITICAL)
- [ ] **Test 10:** Keyboard teleop ✅
- [ ] **Test 11:** Auto-reconnect ✅
- [ ] **Test 12:** Stress test ✅ (optional)

---

## 🐛 Common Issues & Solutions

### Issue: Robot doesn't move when cmd_vel sent

**Check:**
1. Armed status: `ros2 topic echo /robot/armed`
2. Wheel velocities being sent: Add debug print in node
3. STM32 firmware version (must be v2.0+)

**Solution:**
```bash
# Manual ARM first
ros2 service call /robot/arm std_srvs/srv/Trigger

# Then send cmd_vel
ros2 topic pub /cmd_vel geometry_msgs/Twist "{linear: {x: 0.2}}" -1
```

---

### Issue: Wheels spin at wrong speeds

**Check:**
1. Verify parameters in `lyra_params.yaml`:
   - `wheel_radius_m` (measure accurately!)
   - `track_width_m`

**Solution:**
Measure wheel diameter with caliper, update config, rebuild.

---

### Issue: Robot veers to one side

**Possible causes:**
1. Motor calibration (STM32 firmware PID)
2. Encoder direction (check STM32 ENCODER_POLARITY_MAP)
3. Mechanical issues (wheel alignment, friction)

**Not a ROS bridge issue** - check STM32 firmware.

---

### Issue: Telemetry rate too low (<5 Hz)

**Check:**
1. System load: `top`
2. Serial buffer overruns: Check kernel logs `dmesg | grep tty`

**Solution:**
- Reduce other processes on RPi
- Increase telemetry_rate_hz in params (but not >20Hz)

---

## 📈 Performance Metrics

**Target values for Phase 1:**

| Metric | Target | Acceptable | Status |
|--------|--------|------------|--------|
| Telemetry rate | 10 Hz | 8-12 Hz | ☐ |
| Command latency | <50ms | <100ms | ☐ |
| Timeout response | <600ms | <1000ms | ☐ |
| Reconnect time | <3s | <5s | ☐ |
| Packet loss | 0% | <1% | ☐ |

---

## ✅ Phase 1 Completion Criteria

Mark this phase complete when:

- [x] All 12 tests pass
- [x] Robot can be controlled via `/cmd_vel`
- [x] Safety timeout works reliably
- [x] Services functional
- [x] Connection resilient (auto-reconnect)
- [x] Performance within targets
- [x] Documentation complete

---

**Once all tests pass, Phase 1 is COMPLETE!** 🎉  
**Ready to proceed to Phase 2: Odometry & TF**
