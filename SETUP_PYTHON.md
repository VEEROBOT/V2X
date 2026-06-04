# V2X Robot Demo — Setup Guide (Pure Python Stack)

> **Last updated:** 2026-05-27  
> **Stack:** Pure Python — no ROS2, no colcon, no sourcing. Just Python + pip.  
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
│  RSU binary    │  │  Python + OBU  │  │  Python + OBU        │
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

**Do this on BOTH Pis. The process is identical. Do NOT install ROS2.**

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

### 3.3 Enable Camera and UART

Edit `/boot/firmware/config.txt` — add at the bottom:

```
# Pi Camera — required for picamera2 to see the camera
camera_auto_detect=1

# UART for STM32 — disables Bluetooth to free /dev/ttyAMA0
dtoverlay=disable-bt
```

Then disable the Bluetooth service and reboot:

```bash
sudo systemctl disable hciuart
sudo reboot
```

After reboot, verify both work:

```bash
ls /dev/ttyAMA0                  # must exist
libcamera-hello --list-cameras   # must show "Available cameras"
```

If `ttyAMA0` is missing: confirm `dtoverlay=disable-bt` is in `config.txt` and reboot.  
If camera is missing: check the ribbon cable is fully seated.

### 3.4 Fix Serial Port Permission

```bash
sudo usermod -a -G dialout ubuntu
# Then log out and back in (or reboot) for the group to take effect
# Verify:  groups ubuntu   — should include "dialout"
```

---

## PART 4 — Install Python Stack

### 4.1 Install System Packages

```bash
sudo apt install -y \
    python3-pip \
    python3-picamera2 \
    python3-pygame \
    libcap-dev \
    joystick
```

### 4.2 Copy Code to the Pi

From your **Windows PC** (PowerShell):

```powershell
# Replace 192.168.1.x with the Pi's actual IP
scp -r "D:\V2X\robot_python" ubuntu@192.168.1.x:/home/ubuntu/v2x/
```

Or copy via USB drive if WiFi transfer is slow.

### 4.3 Install Python Dependencies

```bash
cd /home/ubuntu/v2x/robot_python
pip install -r requirements.txt
```

`requirements.txt` installs: `pyserial`, `opencv-contrib-python-headless`, `numpy`, `pyyaml`, `pygame`.  
`opencv-contrib` is required — it includes `cv2.aruco` for AprilTag detection.

### 4.4 Verify Hardware Before Continuing

```bash
# Camera
libcamera-hello --list-cameras
# Expected: "Available cameras" listing imx219, imx708, or similar

# Serial port
ls -la /dev/ttyAMA0
# Expected: crw-rw---- 1 root dialout ... /dev/ttyAMA0
# If permission denied when Python opens it: re-check Step 3.4 and log out/in

# Joystick (only if dongle is plugged in)
ls /dev/input/js*         # expect /dev/input/js0
jstest /dev/input/js0     # move sticks, press buttons — note axis/button numbers
```

### 4.5 Manual First-Run Test

Before installing as a service, run once manually to confirm all links are up:

```bash
cd /home/ubuntu/v2x/robot_python

# Car Pi:
python3 main_car.py --serial-port /dev/ttyAMA0

# Ambulance Pi:
python3 main_ambulance.py --serial-port /dev/ttyAMA0
```

Look for these lines in the output (Ctrl+C to stop):

```
Serial connected on /dev/ttyAMA0       ← STM32 link is up
Camera started (picamera2 320x240)     ← camera working
Control socket listening on UDP 5010   ← ready for remote commands
Joystick: found js0                    ← joystick (or "not found" — optional)
```

No `ERROR` or `CRITICAL` lines means you are ready.

If you see a serial error: re-check `dialout` group membership and the TX/RX wiring.

### 4.6 Set Peer IP Addresses

Each robot needs the other robot's IP so they can share position over UDP.

```bash
# Find each Pi's IP:
hostname -I

# On car Pi — edit the service file:
nano /home/ubuntu/v2x/robot_python/v2x_car.service
# Change:   --ambulance-ip 192.168.1.x
# To:       --ambulance-ip <actual ambulance Pi IP>

# On ambulance Pi:
nano /home/ubuntu/v2x/robot_python/v2x_ambulance.service
# Change:   --car-ip 192.168.1.x
# To:       --car-ip <actual car Pi IP>
```

Position sharing is optional — if left blank the car still yields on V2X signal alone,
just without knowing exactly when the ambulance has passed.

### 4.7 Install systemd Service (Auto-Start on Boot)

> `enable` = register for every future boot.  
> `start`  = start immediately (no reboot needed).  
> Run **both** on first deployment.

```bash
# On car Pi:
sudo cp /home/ubuntu/v2x/robot_python/v2x_car.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable v2x_car     # auto-start on every boot
sudo systemctl start v2x_car      # start right now
sudo journalctl -fu v2x_car       # watch logs live (Ctrl+C to stop)

# On ambulance Pi:
sudo cp /home/ubuntu/v2x/robot_python/v2x_ambulance.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable v2x_ambulance
sudo systemctl start v2x_ambulance
sudo journalctl -fu v2x_ambulance
```

Other service commands:

```bash
sudo systemctl status v2x_car      # is it running? exit code?
sudo systemctl restart v2x_car     # restart after a code update
sudo systemctl stop v2x_car        # stop (stays enabled for next boot)
sudo systemctl disable v2x_car     # remove from boot (does not stop it now)
```

After a code update via scp — just restart, no need to re-enable:

```bash
sudo systemctl restart v2x_car
sudo journalctl -fu v2x_car
```

---

## PART 5 — Joystick

The RF joystick (USB dongle) is a **deadman override** — hold a button to take manual control,
release to return to autonomous lane following.

| Action | Effect |
|--------|--------|
| Hold **LB / L1** (button 5) | Joystick controls robot — autonomous pauses |
| Release **LB / L1** | Returns to autonomous lane following immediately |
| Left stick Y (axis 1) | Forward / reverse (up to 0.4 m/s) |
| Right stick X (axis 3) | Steer left / right (up to 1.5 rad/s) |

Joystick axis and button numbers vary by manufacturer. Check yours:

```bash
jstest /dev/input/js0
# Move each stick — watch which Axis number changes
# Press each button — watch which Button number changes
```

Update `config.yaml` if your numbers differ from the defaults:

```yaml
joystick:
  deadman_button: 5    # button to hold for manual control
  axis_throttle:  1    # left stick Y axis
  axis_steering:  3    # right stick X axis
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

- **Platform:** 4 × 4 foam mats (60 cm each) → 2.4 m × 2.4 m, corner radius ≈ 45 cm
- **Perimeter:** ≈ 11 m
- Both robots follow the **white broken centre line** (same path — ambulance is faster so it catches up)

### 6.2 Emergency Sequence

1. **EVADING** — Car turns left for 2 s, moves toward the yellow yield zone
2. **HOLDING** — Car stops and waits; ambulance passes on the centre line
3. **RESUMING** — Car ramps speed back up and returns to centre-line following

### 6.3 AprilTags for Position

AprilTags are printed in the **white centre-line gaps** (replacing dashes), one every 0.5 m, ≈ 22 total around the loop.

```
Tag 0   Tag 1   Tag 2   Tag 3  ...  Tag 21
 |       |       |       |            |
─|─ ─ ─ ─|─ ─ ─ ─|─ ─ ─ ─|─ ...  ─ ─|─
0m      0.5m    1.0m    1.5m       10.5m
```

**Why tags matter:**

| Without position | With position |
|-----------------|---------------|
| Car yields whenever V2X is active | Car yields only when ambulance is behind AND within 2 m |
| Car holds until timeout | Car resumes automatically when ambulance passes its zone |
| Ambulance ahead = car still yields | Ambulance ahead = car ignores the alert |

**Print the tags:**

1. Download from the AprilRobotics GitHub: `apriltag-imgs/tree/master/tag36h11`
2. Files: `tag36_11_00000.png` through `tag36_11_00021.png`
3. Print at **8 cm × 8 cm** (outer black border is part of the tag)
4. Cut, laminate, paste into the white centre-line gaps on the vinyl

**Calibrate focal_px (one-time, on the actual robot):**

```bash
# 1. Place a tag at exactly 0.30 m from the camera
# 2. Run with AprilTag debug:
python3 main_car.py --debug-position
# (requires a display connected or X11 forwarding: ssh -X ubuntu@car-robot.local)

# 3. Measure pixel_width of the tag in the debug window
# 4. focal_px = pixel_width × 0.30 / 0.08
# 5. Edit config.yaml → position: focal_px: <your value>
```

If your track has a different number of tags, edit `config.yaml`:

```yaml
position:
  n_tags: 22          # total tags around the loop
  tag_spacing_m: 0.5  # metres between consecutive tags
  tag_size_m: 0.08    # printed side length in metres
```

---

## PART 7 — Tuning the Line Follower

Colour thresholds depend on your specific vinyl and your lighting. Tune once, then leave.

### 7.1 Run with Debug Image

Requires a display or X11 forwarding (`ssh -X`):

```bash
python3 main_car.py --debug-image
```

The debug window shows:
- **Green line** = frame centre
- **Orange line** = lane target (PID drives the red dot onto this)
- **Red dot** = detected lane centroid

### 7.2 Tune HSV Thresholds

Edit `config.yaml` under `lane_follower`:

```yaml
lane_follower:
  # White broken centre line:
  white_v_low: 190    # lower (try 160) if white looks grey under your lighting

  # Yellow edge bars:
  yellow_h_low:  20   # lower to ~15 if yellow looks orange; raise to 25 if it reads as green
  yellow_s_low:  80   # lower if yellow looks washed out under indoor LED lighting
```

Restart after editing (`Ctrl+C`, then `python3 main_car.py` again — no rebuild needed).

### 7.3 Tune PID

```yaml
lane_follower:
  kp: 0.005    # increase if slow to correct; decrease if it oscillates side to side
  kd: 0.002    # increase if it oscillates even with low kp
  ki: 0.0001   # leave very small; only raise if robot has a persistent one-sided drift
```

Rule of thumb: raise `kp` until it oscillates, halve it, then raise `kd` to smooth.

---

## PART 8 — V2X Platform

### 8.1 Network

All devices must be on the **same WiFi network**:
- Laptop / PC (running desktop server)
- RSU Pi or NUC
- Car Robot Pi
- Ambulance Robot Pi

Find each device's IP:
```bash
hostname -I
```

### 8.2 Desktop — Central Authority

On your Windows PC:

```bash
cd V2X/v2x_testbed/desktop
pip install -r requirements.txt
python server.py
```

Open `http://localhost:5000` — V2X dashboard. Keep this running during the demo.

### 8.3 RSU — Roadside Unit

On the RSU Pi or NUC:

```bash
sudo apt install -y cmake build-essential libssl-dev

cd V2X/v2x_testbed/rsu
mkdir build && cd build
cmake .. && make -j$(nproc)

# Edit config to point to Desktop IP:
nano ../config/rsu_config.json
# Set "desktop_ip" to your laptop's IP

# Run:
./rsu_server ../config/rsu_config.json
```

RSU listens on UDP port 5000.

### 8.4 OBU — Full Automatic V2X (Optional)

Without OBU: use `control_socket.py` to trigger emergency manually (see Part 9).  
With OBU: the ambulance authenticates with the RSU automatically; the RSU notifies the car.

Build OBU on each robot Pi:

```bash
cd V2X/v2x_testbed/obu
mkdir build && cd build
cmake .. && make -j$(nproc)
# Binary: obu/build/obu_client
```

Configure each OBU:

```bash
# Car Pi:
nano /home/ubuntu/v2x/obu/config/obu1_config.json
# Set: rsu_ip = RSU Pi's IP,  is_emergency: false

# Ambulance Pi:
nano /home/ubuntu/v2x/obu/config/obu2_config.json
# Set: rsu_ip = RSU Pi's IP,  is_emergency: true
```

Configure RSU to notify the car:

```bash
nano V2X/v2x_testbed/rsu/config/rsu_config.json
```
```json
{
  "car_alert_ip":   "192.168.1.x",
  "car_alert_port": 5001
}
```

Run robots with OBU binary:

```bash
# Car Pi:
python3 main_car.py \
  --ambulance-ip 192.168.1.x \
  --obu-binary /home/ubuntu/v2x/obu/build/obu_client \
  --obu-config /home/ubuntu/v2x/obu/config/obu1_config.json

# Ambulance Pi:
python3 main_ambulance.py \
  --car-ip 192.168.1.x \
  --obu-binary /home/ubuntu/v2x/obu/build/obu_client \
  --obu-config /home/ubuntu/v2x/obu/config/obu2_config.json
```

How the automatic loop works:

```
Ambulance OBU → RSU (authenticate)
  → RSU sends {"type":"EMERGENCY_ACTIVE"} to car_alert_ip:5001
    → v2x_bridge.py on Car Pi receives it
      → emergency_handler triggers EVADING → HOLDING

Ambulance OBU session expires
  → RSU sends {"type":"EMERGENCY_CLEARED"}
    → emergency_handler resumes NORMAL
```

---

## PART 9 — Manual Emergency Control (No OBU)

For testing without OBU hardware. From any terminal on the network:

```bash
cd /home/ubuntu/v2x/robot_python

# Ambulance Pi — trigger emergency (car should yield):
python3 control_socket.py --port 5011 emergency_on

# Ambulance Pi — clear emergency (car should resume):
python3 control_socket.py --port 5011 emergency_off

# Car Pi — arm / disarm motors:
python3 control_socket.py --port 5010 arm
python3 control_socket.py --port 5010 disarm

# Car Pi — immediate stop:
python3 control_socket.py --port 5010 estop

# Car Pi — check status:
python3 control_socket.py --port 5010 status

# From another machine on the same WiFi:
python3 control_socket.py --host 192.168.1.x --port 5010 emergency_on
```

---

## PART 10 — Troubleshooting

### Robot doesn't move

```bash
# Check if armed
python3 control_socket.py --port 5010 status

# Arm manually
python3 control_socket.py --port 5010 arm

# Watch live logs for errors
sudo journalctl -fu v2x_car
```

### Camera not found / picamera2 error

```bash
libcamera-hello --list-cameras
# If blank: check ribbon cable, confirm camera_auto_detect=1 in /boot/firmware/config.txt, reboot
```

If you want to use a USB webcam instead of Pi Camera:

```yaml
# config.yaml:
camera:
  use_picamera2: false
  device: 0
```

### Serial port not found / STM32 not connecting

```bash
ls /dev/ttyAMA0              # must exist
groups ubuntu                # must include "dialout"

# If dialout is missing:
sudo usermod -a -G dialout ubuntu
# then log out and back in
```

Check wiring: STM32 TX → Pi GPIO15 (Pin 10), STM32 RX → Pi GPIO14 (Pin 8).  
TX and RX must be **crossed** — one side's TX goes to the other side's RX.

### Joystick not responding

```bash
ls /dev/input/js*            # must show js0
jstest /dev/input/js0        # move sticks — axis numbers should change
```

If wrong axis/button numbers, edit `config.yaml` under `joystick:`.

### Lane follower not detecting line

Run with `--debug-image` (needs display or `ssh -X`):

```bash
python3 main_car.py --debug-image
```

If the red dot is not visible: your HSV thresholds don't match your lighting.  
Lower `white_v_low` in `config.yaml` if white looks grey. See Part 7.

### V2X emergency not triggering on car

Check the car's control socket is reachable:

```bash
# From any machine on the same WiFi:
python3 control_socket.py --host <car-pi-ip> --port 5010 status

# Verify port 5001 is listening (OBU mode):
ss -ulnp | grep 5001
```

---

## Configuration Reference

All parameters in `config.yaml`. Key values to confirm before first run:

```yaml
serial:
  port: /dev/ttyAMA0        # verify with: ls /dev/ttyAMA*

camera:
  use_picamera2: true        # true = Pi Camera CSI; false = USB webcam

joystick:
  deadman_button: 5          # verify with jstest /dev/input/js0
  axis_throttle:  1          # left stick Y
  axis_steering:  3          # right stick X
```

Per-robot differences (set in main files, not config):

| Setting | Car | Ambulance |
|---------|-----|-----------|
| Linear speed | 0.20 m/s | 0.28 m/s |
| Control socket port | 5010 | 5011 |
| Has emergency handler | Yes | No — drives through |

---

## Quick Reference

```bash
# ── On car Pi ─────────────────────────────────────────────────────────────────
python3 main_car.py --ambulance-ip 192.168.1.x          # run manually
sudo systemctl start v2x_car                             # start via service
sudo systemctl restart v2x_car                           # after code update
sudo journalctl -fu v2x_car                              # live logs

# ── On ambulance Pi ───────────────────────────────────────────────────────────
python3 main_ambulance.py --car-ip 192.168.1.x
sudo systemctl start v2x_ambulance
sudo journalctl -fu v2x_ambulance

# ── Joystick ──────────────────────────────────────────────────────────────────
jstest /dev/input/js0                                    # find axis/button numbers
# While robot is running: hold LB (button 5) = manual, release = autonomous

# ── Manual emergency (no OBU) ─────────────────────────────────────────────────
python3 control_socket.py --port 5011 emergency_on       # ambulance triggers
python3 control_socket.py --port 5011 emergency_off      # ambulance clears
python3 control_socket.py --port 5010 arm                # arm car motors
python3 control_socket.py --port 5010 estop              # immediate stop
python3 control_socket.py --port 5010 status             # check state

# ── Debug (needs display or ssh -X) ───────────────────────────────────────────
python3 main_car.py --debug-image                        # lane detection window
python3 main_car.py --debug-position                     # AprilTag window
```
