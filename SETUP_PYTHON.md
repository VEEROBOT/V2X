# V2X Robot Setup Guide

> **Last updated:** 2026-06-08  
> **Hardware:** Raspberry Pi 5, Ubuntu 24.04 LTS, Arducam B0390 / IMX219 camera  
> **Stack:** Pure Python — no ROS2 needed.

---

## Quick Start (the short version)

```
1. Flash Ubuntu 24.04 to SD card
2. Boot Pi, update, clone repo
3. Edit 1 line in the OBU config (RSU IP)
4. sudo bash setup.sh car        ← does everything automatically
5. sudo reboot
```

That's it. Details below.

---

## Step 1 — Flash Ubuntu 24.04

1. Download **Raspberry Pi Imager**
2. Choose **Ubuntu Server 24.04 LTS (64-bit)**
3. In Imager advanced settings (before flashing):
   - Hostname: `car-robot` or `ambulance-robot`
   - Enable SSH
   - WiFi credentials
   - Username: `veerobot` (or your choice — update the service files if different)
4. Flash to microSD (32 GB+), insert, power on
5. Wait ~90 seconds, then SSH in:

```bash
ssh veerobot@car-robot.local
sudo apt update && sudo apt upgrade -y
```

---

## Step 2 — Clone the repo

```bash
git clone https://github.com/VEEROBOT/V2X.git ~/projects/V2X
cd ~/projects/V2X
```

---

## Step 3 — Edit the one thing that changes per robot

Open the OBU config for this robot and set `rsu_ip` to the **WiFi IP of the laptop running the RSU**:

**Car:**
```bash
nano v2x_testbed/obu/config/obu1_config.json
```
```json
"rsu_ip": "192.168.x.x"     ← your laptop's WiFi IP
```

**Ambulance:**
```bash
nano v2x_testbed/obu/config/obu2_config.json
```
```json
"rsu_ip": "192.168.x.x"     ← same laptop WiFi IP
```

> That's the only file you need to edit. Everything else is set up by the script.

---

## Step 4 — Run setup.sh

```bash
cd ~/projects/V2X/robot_python
sudo bash setup.sh car          # for car robot
# OR
sudo bash setup.sh ambulance    # for ambulance robot
```

This takes **5–10 minutes** on first run (libcamera Python bindings compile from source).
Subsequent runs skip completed steps and finish in under a minute.

**What the script does:**
| Step | Action |
|------|--------|
| 1 | Installs system packages (picamera2, pygame, cmake, etc.) |
| 2 | Adds Raspberry Pi apt repo, installs libcamera 0.5 |
| 3 | Builds Python 3.12 libcamera bindings from source *(Pi 5 + Ubuntu 24.04 requirement)* |
| 4 | Creates Python venv (`--system-site-packages`) |
| 5 | Installs pip packages (pyserial, opencv, numpy, etc.) |
| 6 | Patches picamera2 for headless operation |
| 7 | Sets `/boot/firmware/config.txt` (camera overlay, UART) |
| 8 | Removes serial console from `cmdline.txt` (frees `/dev/ttyAMA0` for STM32) |
| 9 | Adds user to `dialout` group |
| 10 | Builds OBU binary (`v2x_testbed/obu/build/obu_client`) |
| 11 | Installs and enables `v2x_car` or `v2x_ambulance` systemd service |

---

## Step 5 — Reboot

```bash
sudo reboot
```

After reboot, the robot starts automatically. Check it:

```bash
sudo journalctl -fu v2x_car         # car
sudo journalctl -fu v2x_ambulance   # ambulance
```

You should see:
```
Camera: picamera2  320x240
Joystick: 'Xbox 360 Controller'  deadman=btn4  turbo=btn5  arm=btn7
RSU alert listener started on UDP port 5001
V2X CAR ROBOT READY
```

---

## Hardware Wiring

### Each robot needs

| Component | Connection |
|-----------|-----------|
| STM32F405 | UART to RPi GPIO14 (TX) / GPIO15 (RX) |
| Camera (IMX219 / Arducam B0390) | CSI ribbon to **CAM/DISP 0** port *(not port 1)* |
| RF joystick USB dongle | Any USB port |
| Battery 5V BEC | Powers the Pi |

### STM32 UART wiring

```
STM32 TX  →  RPi GPIO15  (Pin 10, UART RX)
STM32 RX  →  RPi GPIO14  (Pin 8,  UART TX)
STM32 GND →  RPi GND     (Pin 6)
```

> Shared GND only — do NOT connect STM32 power to RPi 3.3V.  
> Use a 3.3V level-shifter if your STM32 runs at 5V logic.

---

## STM32 Firmware

Flash once per board. Both robots use identical firmware.

1. Open `V2X/STM32F405RGTx` in STM32CubeIDE
2. Build (`Ctrl+B`) and flash (Run button)
3. Board waits for Pi UART — no further config needed

---

## Joystick Controls

| Button/Stick | Action |
|---|---|
| Hold **LB** (btn 4) | Enable joystick — autonomous pauses |
| Hold **LB + RB** (btn 4+5) | Turbo mode (0.8 m/s) |
| Press **Start** (btn 7) | Arm / Disarm toggle |
| Left stick Y | Forward / reverse |
| Right stick X | Steer left / right |

Run `jstest /dev/input/js0` to verify button/axis numbers match your controller.  
Edit `config.yaml` under `joystick:` if they differ.

---

## V2X Network Setup

All devices must be on the **same WiFi network**.

```
Laptop (RSU + Desktop)
  ├── RSU binary listening on UDP 5000
  └── Desktop Flask server on HTTP 5000

Car Pi (192.168.x.x)
  └── v2x_bridge listening on UDP 5001 ← RSU sends alerts here

Ambulance Pi (192.168.x.x)
  └── OBU2 connects to RSU → triggers emergency → RSU alerts car
```

### On the laptop — RSU config

Edit `V2X/v2x_testbed/rsu/config/rsu_config.json`:

```json
"car_alert_ip":  "192.168.x.x",    ← car Pi's WiFi IP
"car_alert_port": 5001
```

Restart the RSU after changing this. You should see:
```
[RSU] Car alert target: 192.168.x.x:5001
```

### Test the V2X chain (no ambulance robot needed)

From the laptop, simulate an RSU alert:

```python
python3 -c "
import socket, json, time
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.sendto(json.dumps({'type':'EMERGENCY_ACTIVE','session_id':'test-001'}).encode(), ('192.168.x.x', 5001))
print('Alert sent'); time.sleep(5)
s.sendto(json.dumps({'type':'EMERGENCY_CLEARED','session_id':'test-001'}).encode(), ('192.168.x.x', 5001))
print('Clear sent')
"
```

Car should log: `EMERGENCY ACTIVE → EVADING → HOLDING → RESUMING → NORMAL`

---

## Per-robot differences

| Setting | Car | Ambulance |
|---------|-----|-----------|
| Service | `v2x_car` | `v2x_ambulance` |
| OBU config | `obu1_config.json` (`is_emergency: false`) | `obu2_config.json` (`is_emergency: true`) |
| Main script | `main_car.py` | `main_ambulance.py` |
| Control socket port | 5010 | 5011 |
| Emergency handler | Yes (yields to ambulance) | No (drives through) |
| Linear speed | 0.20 m/s | 0.28 m/s |

---

## Manual control (no autonomous)

```bash
# Arm/disarm from another terminal:
cd ~/projects/V2X/robot_python && source .venv/bin/activate
python3 control_socket.py --port 5010 arm
python3 control_socket.py --port 5010 disarm
python3 control_socket.py --port 5010 estop
python3 control_socket.py --port 5010 status

# Trigger emergency manually (test without OBU):
python3 control_socket.py --port 5010 emergency_on
python3 control_socket.py --port 5010 emergency_off
```

---

## Useful commands

```bash
# Service management
sudo systemctl start   v2x_car
sudo systemctl stop    v2x_car
sudo systemctl restart v2x_car          # after code/config change
sudo journalctl -fu    v2x_car          # live logs

# Camera test (take a snap, view in VS Code)
cd ~/projects/V2X/robot_python && source .venv/bin/activate
python3 -c "
import picamera2, time
cam = picamera2.Picamera2()
cam.configure(cam.create_preview_configuration(main={'size':(320,240),'format':'BGR888'}))
cam.start(); time.sleep(2)
cam.capture_file('/tmp/camera_test.jpg')
cam.stop(); print('Saved /tmp/camera_test.jpg')
"

# Joystick mapping
jstest /dev/input/js0

# Live drive diagnostics (motors + telemetry)
cd ~/projects/V2X/robot_python && source .venv/bin/activate
python3 diag_drive.py
```

---

## Troubleshooting

### Camera not working
```bash
# Test with Python (libcamera-hello won't work on Ubuntu 24.04)
cd ~/projects/V2X/robot_python && source .venv/bin/activate
python3 -c "import picamera2; cam=picamera2.Picamera2(); print(cam.camera_properties)"
```
- Check ribbon cable is in **CAM/DISP 0** port
- Check `dmesg | grep imx219` — should show `registered` not `probe failed`
- Re-run `sudo bash setup.sh car` if libcamera was not built

### Serial / STM32 not connecting
```bash
ls -la /dev/ttyAMA0         # must exist
groups                      # must include dialout (may need re-login)
```

### Robot not arming
Press **Start** button (btn 7) — robot starts in armed state but joystick can disarm it.  
Or: `python3 control_socket.py --port 5010 arm`

### V2X alert not received on car
```bash
sudo journalctl -u v2x_car | grep "RSU alert listener"
# Must show: RSU alert listener started on UDP port 5001
# If not: check config.yaml  v2x_bridge: manual_mode: false
```
Check RSU config has correct `car_alert_ip` and that both Pi and laptop are on same WiFi.
