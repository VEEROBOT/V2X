# V2X Robot Demo — Setup Guide (ROS2 Stack)

> **Last updated:** 2026-05-27  
> **Stack:** ROS2 Humble — requires colcon build, sourcing, and ROS2 tooling.  
> **Robots:** Car Pi + Ambulance Pi, each with STM32F405 motor controller.

---

## What You Are Building

Two 4WD robots drive around a printed vinyl road following a white centre line.  
When the **Ambulance** appears, it broadcasts a V2X emergency signal.  
The **Car** receives this, moves left (Indian road rules), and resumes once the ambulance passes.

```
┌─────────────────────────────────────────────────────────────────┐
│  LAPTOP / PC                                                    │
│  V2X Dashboard + Central Authority (Python Flask)               │
└───────────────────────────┬─────────────────────────────────────┘
                            │ WiFi (TCP/UDP)
          ┌─────────────────┼──────────────────┐
          │                 │                  │
┌─────────▼──────┐  ┌───────▼────────┐  ┌──────▼───────────────┐
│  RSU           │  │  CAR ROBOT     │  │  AMBULANCE ROBOT     │
│  RPi 5 / NUC   │  │  Raspberry Pi  │  │  Raspberry Pi        │
│  RSU binary    │  │  ROS2 + OBU    │  │  ROS2 + OBU          │
└────────────────┘  │  ↕ UART        │  │  ↕ UART              │
                    │  STM32F405     │  │  STM32F405           │
                    │  4WD Motors    │  │  4WD Motors          │
                    │  Pi Camera     │  │  Pi Camera           │
                    └────────────────┘  └──────────────────────┘
```

---

## PART 1 — Hardware Wiring

### Each Robot Has

| Component | Connection |
|-----------|-----------|
| STM32F405 board | UART TX/RX to Raspberry Pi GPIO 14/15 |
| Raspberry Pi | Powers from robot battery (5V BEC) |
| Camera (Pi Camera Module v2 or v3) | CSI ribbon cable to RPi camera port |
| 4x DC motors + encoders | Connected to STM32 motor driver |
| RF joystick dongle | USB port on Raspberry Pi |

### STM32 → Raspberry Pi Serial Wiring

```
STM32 TX  →  RPi GPIO15 (UART RX, Pin 10)
STM32 RX  →  RPi GPIO14 (UART TX, Pin 8)
STM32 GND →  RPi GND   (Pin 6)
```

> Do NOT connect STM32 power to RPi 3.3V — shared GND only.  
> If your STM32 runs at 5V logic, use a 3.3V level shifter on the UART lines.

### Camera Mounting

- Use **Pi Camera Module v2 or v3** — CSI ribbon cable into the camera port
- Mount at the **front-bottom** of the robot, angled **30–45° downward** to see the road ahead

---

## PART 2 — STM32 Firmware

**Flash once per board. Both Car and Ambulance use identical firmware.**

### Tools

- [STM32CubeIDE](https://www.st.com/en/development-tools/stm32cubeide.html) — free, install on Windows
- USB cable (Micro-USB or USB-C depending on your board)

### Steps

1. **Open the project**  
   STM32CubeIDE → `File` → `Open Projects from File System`  
   Browse to `V2X/STM32F405RGTx` → click Finish

2. **Build**  
   Click the hammer icon or `Ctrl+B` — wait for "Build Finished" with 0 errors

3. **Flash**  
   Connect STM32 via USB → click the play/debug icon → `Run As` → `STM32 Cortex-M C/C++ Application`  
   It flashes automatically and reboots

4. **Verify**  
   The OLED shows status. The board waits for the Pi to connect over serial.

> **You do not need to change any STM32 code.** It is pre-configured to:
> - Accept Lyra binary commands from the Pi over UART at 115200 baud
> - Run closed-loop PID motor control using wheel encoders
> - Send encoder telemetry back to the Pi over UART

---

## PART 3 — Raspberry Pi Setup

**Do this on BOTH Pis. The process is identical.**

### 3.1 Install Ubuntu Server

1. Download **Raspberry Pi Imager** from raspberrypi.com
2. Flash **Ubuntu Server 22.04 LTS (64-bit)** to a microSD (16 GB+)
3. In Imager settings before flashing:
   - Hostname: `car-robot` (or `ambulance-robot`)
   - Enable SSH
   - Set WiFi credentials
   - Username: `ubuntu` / password: your choice

> Ubuntu Server on Raspberry Pi uses `ubuntu` as the default username.

### 3.2 First Boot

```bash
ssh ubuntu@car-robot.local
sudo apt update && sudo apt upgrade -y
```

### 3.3 Install ROS2 Humble

```bash
# Add ROS2 apt repository
sudo apt install -y software-properties-common curl
sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
  -o /usr/share/keyrings/ros-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] \
  http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo $UBUNTU_CODENAME) main" \
  | sudo tee /etc/apt/sources.list.d/ros2.list

# Install ROS2 Humble base
sudo apt update
sudo apt install -y ros-humble-ros-base python3-colcon-common-extensions

# Load ROS2 in every terminal
echo "source /opt/ros/humble/setup.bash" >> ~/.bashrc
source ~/.bashrc
```

### 3.4 Install Package Dependencies

```bash
sudo apt install -y \
  ros-humble-cv-bridge \
  ros-humble-image-transport \
  ros-humble-sensor-msgs \
  ros-humble-geometry-msgs \
  ros-humble-nav-msgs \
  ros-humble-robot-localization \
  ros-humble-joy \
  ros-humble-teleop-twist-joy \
  python3-opencv \
  python3-pip \
  libcamera-dev \
  libcamera-apps \
  joystick
```

> **AprilTag support requires opencv-contrib.**  
> The `python3-opencv` apt package does NOT include `cv2.aruco`.  
> Install the contrib build via pip after the apt step:
> ```bash
> pip install opencv-contrib-python-headless
> ```

### 3.5 Enable UART and Camera

Edit `/boot/firmware/config.txt` — add at the bottom:

```
# Pi Camera
camera_auto_detect=1

# UART for STM32 — disables Bluetooth to free /dev/ttyAMA0
dtoverlay=disable-bt
```

```bash
sudo systemctl disable hciuart
sudo reboot
```

After reboot, verify:

```bash
ls /dev/ttyAMA0                  # must exist
libcamera-hello --list-cameras   # must show "Available cameras"
```

### 3.6 Fix Serial Port Permission

```bash
sudo usermod -a -G dialout ubuntu
# Log out and back in (or reboot)
# Verify:  groups ubuntu   should include "dialout"
```

### 3.7 Copy Code to the Pi

From your **Windows PC** (PowerShell):

```powershell
scp -r "D:\V2X\ROS_Code\src" ubuntu@192.168.1.x:/home/ubuntu/ros2_ws/src
```

### 3.8 Build the ROS2 Workspace

```bash
cd ~/ros2_ws

# Install any missing dependencies
rosdep init      # only needed once on a fresh Pi
rosdep update
rosdep install --from-paths src --ignore-src -r -y

# Build all packages
colcon build --symlink-install

# Load the built packages
source install/setup.bash
echo "source ~/ros2_ws/install/setup.bash" >> ~/.bashrc
```

> First build takes 5–10 minutes on a Pi 4. Subsequent builds are faster.  
> If you see `colcon: command not found`: `sudo apt install python3-colcon-common-extensions`

### 3.9 Verify the Build

```bash
ros2 pkg list | grep -E "lyra|v2x|camera"
```

Expected:
```
camera_ros
lyra_bridge
lyra_cmd_vel_gate
lyra_config
lyra_localization
v2x_robot
```

---

## PART 4 — V2X Platform Setup

### 4.1 Desktop — Central Authority

On your **Windows PC**:

```bash
cd V2X/v2x_testbed/desktop
pip install -r requirements.txt
python server.py
```

Open `http://localhost:5000` — V2X dashboard. Keep this running during the demo.

### 4.2 RSU — Roadside Unit

On the RSU Pi or NUC:

```bash
sudo apt install -y cmake build-essential libssl-dev

cd V2X/v2x_testbed/rsu
mkdir build && cd build
cmake .. && make -j$(nproc)

# Edit config to point to Desktop IP:
nano ../config/rsu_config.json
# Set "desktop_ip" to your laptop's IP

./rsu_server ../config/rsu_config.json
```

RSU listens on UDP port 5000.

### 4.3 OBU — On-Board Units

> Without OBU: trigger emergency manually via `ros2 service call` (see Part 5).  
> With OBU: ambulance authenticates to RSU automatically; RSU notifies the car.

Build on each robot Pi:

```bash
cd V2X/v2x_testbed/obu
mkdir build && cd build
cmake .. && make -j$(nproc)
```

Configure each OBU:

```bash
# Car:
nano /home/ubuntu/v2x/obu/config/obu1_config.json
# Set: rsu_ip = RSU Pi's IP, is_emergency: false

# Ambulance:
nano /home/ubuntu/v2x/obu/config/obu2_config.json
# Set: rsu_ip = RSU Pi's IP, is_emergency: true
```

Configure RSU to notify car:

```json
{
  "car_alert_ip":   "192.168.1.x",
  "car_alert_port": 5001
}
```

---

## PART 5 — Running the Demo

### 5.1 Network

All devices on the **same WiFi network**. Find IPs:
```bash
hostname -I
```

### 5.2 Start Order

**1. Desktop:**
```bash
python server.py
```

**2. RSU:**
```bash
./rsu_server ../config/rsu_config.json
```

**3. Car Robot Pi:**
```bash
# Without position sharing:
ros2 launch v2x_robot car.launch.py

# With ambulance position sharing (recommended):
ros2 launch v2x_robot car.launch.py ambulance_ip:=192.168.1.x
```

**4. Ambulance Robot Pi:**
```bash
ros2 launch v2x_robot ambulance.launch.py car_ip:=192.168.1.x
```

### 5.3 Arm the Robots

```bash
ros2 service call /lyra/arm std_srvs/srv/Trigger {}
```

### 5.4 Test Emergency (Manual Mode — No OBU)

Trigger from ambulance Pi:
```bash
ros2 service call /v2x/set_emergency std_srvs/srv/SetBool "{data: true}"
```

Clear:
```bash
ros2 service call /v2x/set_emergency std_srvs/srv/SetBool "{data: false}"
```

### 5.5 Full OBU Launch

```bash
# Car Pi:
ros2 launch v2x_robot car.launch.py \
  ambulance_ip:=192.168.1.x \
  obu_binary:=/home/ubuntu/v2x/obu/build/obu_client \
  obu_config:=/home/ubuntu/v2x/obu/config/obu1_config.json

# Ambulance Pi:
ros2 launch v2x_robot ambulance.launch.py \
  car_ip:=192.168.1.x \
  obu_binary:=/home/ubuntu/v2x/obu/build/obu_client \
  obu_config:=/home/ubuntu/v2x/obu/config/obu2_config.json
```

Full automatic loop:
```
Ambulance OBU → RSU (authenticate)
  → RSU sends {"type":"EMERGENCY_ACTIVE"} to car_alert_ip:5001
    → v2x_bridge_node sets /v2x/emergency_detected = true
      → emergency_handler_node triggers EVADING → HOLDING

Ambulance session expires
  → RSU sends {"type":"EMERGENCY_CLEARED"}
    → emergency_handler resumes NORMAL
```

---

## PART 6 — Road Layout and AprilTags

### 6.1 Physical Road

```
← ~1 metre wide (2.4 m × 2.4 m rounded square loop) →

[Black]──────────────────────────────────────────────[Black]
│   Black road   │  Yellow ─ ─  │  White ─ ─ ─  │   Black road   │
│                │  yield zone  │  centre line  │                │
[Black]──────────────────────────────────────────────[Black]
```

- **Platform:** 4 × 4 foam mats (60 cm) → 2.4 m × 2.4 m, corner radius ≈ 45 cm
- **Perimeter:** ≈ 11 m
- Both robots follow the **white broken centre line**

### 6.2 Emergency Sequence

1. **EVADING** — Car turns left 2 s toward yellow yield zone
2. **HOLDING** — Car stops; ambulance passes on centre line
3. **RESUMING** — Car ramps back up, returns to centre-line following

### 6.3 AprilTags

Printed in white centre-line gaps, one every 0.5 m, ≈ 22 total.

**Print the tags:**
1. Download from AprilRobotics GitHub: `apriltag-imgs/tree/master/tag36h11`
2. Files: `tag36_11_00000.png` through `tag36_11_00021.png`
3. Print at **8 cm × 8 cm**
4. Cut, laminate, paste into white centre-line gaps

**Calibrate focal_px:**
```bash
# Place a tag at exactly 0.30 m from camera
ros2 launch v2x_robot car.launch.py debug_position:=true
ros2 run rqt_image_view rqt_image_view   # select /position/debug

# Measure pixel_width of tag in the image
# focal_px = pixel_width × 0.30 / 0.08
# Edit config/position.yaml → focal_px: <your value>
```

Edit `config/position.yaml` if your track has a different tag count:
```yaml
n_tags: 22
tag_spacing_m: 0.5
tag_size_m: 0.08
```

---

## PART 7 — Tuning the Line Follower

### 7.1 Enable Debug Image

```bash
ros2 launch v2x_robot car.launch.py debug_image:=true
ros2 run rqt_image_view rqt_image_view   # select /line_follower/debug
```

Debug overlays:
- **Green line** = frame centre
- **Orange line** = lane target
- **Red dot** = detected lane centroid (PID drives this onto the orange line)

### 7.2 Tune HSV Thresholds

Edit `ROS_Code/src/v2x_robot/config/line_follower.yaml`:

```yaml
white_v_low: 190    # lower (try 160) if white looks grey under your lighting
yellow_h_low:  20   # lower to ~15 if yellow looks orange
yellow_s_low:  80   # lower if yellow looks washed out
```

Restart the launch — no recompile needed (`--symlink-install` reads the file live).

### 7.3 Tune PID

```yaml
kp: 0.005    # raise if slow to correct; lower if it oscillates
kd: 0.002    # raise if oscillates even with low kp
ki: 0.0001   # leave very small
```

---

## PART 8 — Updating Code on the Pi

After editing on Windows:

```powershell
# From PowerShell on PC:
scp -r "D:\V2X\ROS_Code\src\v2x_robot" ubuntu@192.168.1.x:/home/ubuntu/ros2_ws/src/
```

On the Pi — rebuild only the changed package:

```bash
cd ~/ros2_ws
colcon build --packages-select v2x_robot --symlink-install
source install/setup.bash
```

---

## PART 9 — Troubleshooting

### Robot doesn't move

```bash
ros2 topic echo /lyra/armed
ros2 service call /lyra/arm std_srvs/srv/Trigger {}
ros2 topic echo /cmd_vel
```

### Camera not found

```bash
libcamera-hello --list-cameras
# If blank: check ribbon cable, confirm camera_auto_detect=1 in config.txt, reboot
```

### Serial port not found / STM32 not connecting

```bash
ls /dev/ttyAMA0
groups ubuntu        # must include "dialout"
sudo usermod -a -G dialout ubuntu   # if missing — then log out/in
```

### Line follower not detecting lane

```bash
ros2 launch v2x_robot car.launch.py debug_image:=true
ros2 run rqt_image_view rqt_image_view   # select /line_follower/debug
```

Lower `white_v_low` in `config/line_follower.yaml` if white looks grey.

### V2X emergency not triggering on car

Manual mode — trigger directly on car Pi:
```bash
ros2 service call /v2x/set_emergency std_srvs/srv/SetBool "{data: true}"
```

OBU mode — check RSU config has correct `car_alert_ip` and port 5001 is not firewalled:
```bash
ss -ulnp | grep 5001
```

---

## Quick Reference

```bash
# ── Build ─────────────────────────────────────────────────────────────────────
cd ~/ros2_ws
colcon build --symlink-install
source install/setup.bash

# ── Run robots ────────────────────────────────────────────────────────────────
ros2 launch v2x_robot car.launch.py ambulance_ip:=192.168.1.x
ros2 launch v2x_robot ambulance.launch.py car_ip:=192.168.1.x

# ── Arm / stop ────────────────────────────────────────────────────────────────
ros2 service call /lyra/arm std_srvs/srv/Trigger {}
ros2 service call /lyra/emergency_stop std_srvs/srv/Trigger {}

# ── Manual emergency ──────────────────────────────────────────────────────────
ros2 service call /v2x/set_emergency std_srvs/srv/SetBool "{data: true}"
ros2 service call /v2x/set_emergency std_srvs/srv/SetBool "{data: false}"

# ── Monitor ───────────────────────────────────────────────────────────────────
ros2 node list
ros2 topic echo /cmd_vel
ros2 topic echo /v2x/emergency_detected

# ── Debug image ───────────────────────────────────────────────────────────────
ros2 launch v2x_robot car.launch.py debug_image:=true
ros2 run rqt_image_view rqt_image_view

# ── Rebuild one package ───────────────────────────────────────────────────────
colcon build --packages-select v2x_robot --symlink-install
```
