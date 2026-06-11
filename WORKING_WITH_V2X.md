# Working With V2X — Complete Operations Guide

> Last updated: 2026-06-11  
> Stack: Pure Python — no ROS2.  
> Arena: 10 ft × 12 ft, ArduCam 8MP IMX219, STM32 motor controller.

---

## Table of Contents

1. [What Runs Where](#what-runs-where)
2. [Network Layout](#network-layout)
3. [Step-by-Step Activation](#step-by-step-activation)
4. [Viewing the Live Camera Stream](#viewing-the-live-camera-stream)
5. [Joystick Controls](#joystick-controls)
6. [AprilTag Layout](#apriltag-layout)
7. [Testing the Emergency Chain](#testing-the-emergency-chain)
8. [Multiple Robots — Can You Scale Up?](#multiple-robots--can-you-scale-up)
9. [Useful Commands](#useful-commands)
10. [Key Config Files](#key-config-files)
11. [Git Workflow](#git-workflow)
12. [Adding a New Robot](#adding-a-new-robot)
13. [Port Reference](#port-reference)
14. [Troubleshooting](#troubleshooting)

---

## What Runs Where

```
LAPTOP  (e.g. 192.168.0.103)
  ├── Desktop server    python3 server.py          → Dashboard  http://localhost:5000
  └── RSU binary        ./rsu_server rsu_config.json
        ├── UDP 5000  ← OBU authentication
        ├── TCP 8001  ← OBU entity registration
        ├── TCP 8002  ← RSU entity registration
        ├── TCP 9000  ← audit log from RSU
        └── UDP 5001 broadcast → EMERGENCY_ACTIVE / EMERGENCY_CLEARED to all robots

CAR PI  (e.g. 192.168.0.100)
  └── systemd: v2x_car → main_car.py        starts DISARMED — press Start to arm
        ├── Camera (ArduCam 8MP, picamera2, 320×240)
        ├── STM32 motor controller  /dev/ttyRobot
        ├── Joystick  /dev/input/js0  (auto-detects)
        ├── Lane follower + position estimator
        ├── OBU client  (authenticates once, session lasts 5 min)
        ├── RSU alert listener  UDP 5001 ← receives EMERGENCY_ACTIVE
        ├── Position broadcaster  UDP 5002 ↔ ambulance
        └── Vision stream  http://car-ip:5005/    ← open in desktop browser

AMBULANCE PI  (e.g. 192.168.0.104)
  └── systemd: v2x_ambulance → main_ambulance.py   starts ARMED automatically
        ├── Camera, STM32, Joystick  (same as car)
        ├── Lane follower + position estimator
        ├── OBU client  (loops forever — keeps emergency flag active)
        ├── Position broadcaster  UDP 5002 ↔ car
        └── Vision stream  http://ambulance-ip:5005/
```

---

## Network Layout

| Device | IP (example) | What it runs |
|--------|-------------|--------------|
| Laptop | `192.168.0.103` | RSU binary + Desktop server |
| Car Pi | `192.168.0.100` | `v2x_car` systemd service |
| Ambulance Pi | `192.168.0.104` | `v2x_ambulance` systemd service |

**All devices must be on the same WiFi network.**  
The RSU broadcasts emergency alerts to `192.168.0.255` (subnet broadcast) — every robot on the subnet receives them automatically regardless of how many there are.

---

## Step-by-Step Activation

### Order matters: Desktop → RSU → Pis

The Desktop distributes public keys. RSU must register with Desktop **before** any OBU does.

---

### STEP 0 — First time only: clear old keys and sessions

On the **laptop**:
```bash
cd ~/V2X/v2x_testbed
rm -f database/v2x_testbed.db database/master_secret.bin
rm -rf rsu/build/keys/
```

On **each Pi** (SSH in first):
```bash
rm -rf ~/projects/V2X/robot_python/keys/
```

Skip this step on normal restarts once everything works.

---

### STEP 1 — Laptop: start the Desktop server

```bash
cd ~/V2X/v2x_testbed/desktop
python3 server.py
```

Expected output:
```
OBU registration: port 8001
RSU registration: port 8002
Log receiver:     port 9000
Dashboard:        http://localhost:5000
```

Open `http://localhost:5000` in a browser. Leave this terminal running.

---

### STEP 2 — Laptop: start the RSU (new terminal)

```bash
cd ~/V2X/v2x_testbed/rsu/build
./rsu_server ../config/rsu_config.json
```

Expected output:
```
[RSU] ΔTS tolerance: 500 ms
[RSU] Car alert target: 192.168.0.255:5001
```

Desktop terminal shows: `[REG] RSU registered`  
Dashboard: ENTITIES = 1

Leave this terminal running.

---

### STEP 3 — Car Pi: power on and check logs

The `v2x_car` service starts automatically on boot. After powering on, wait ~30 seconds, then:

```bash
ssh veerobot@car-robot.local
sudo journalctl -fu v2x_car
```

Expected log:
```
Camera: picamera2  320×240
Joystick: 'Xbox 360 Controller'  deadman=btn4  turbo=btn5  arm=btn7
RSU alert listener started on UDP port 5001
Vision stream at http://<robot-ip>:5005/
V2X CAR ROBOT READY
[OBU] SESSION ESTABLISHED SUCCESSFULLY
```

> **The car starts DISARMED.** Motors will not move until you arm it.  
> **To arm:** press the **Start button (btn 7)** on the joystick.  
> **To arm remotely** (no joystick attached):
> ```bash
> # From laptop — replace IP with the car's actual IP
> python3 -c "import socket,json; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.sendto(json.dumps({'cmd':'arm'}).encode(), ('192.168.0.100', 5010))"
> ```

---

### STEP 4 — Ambulance Pi: power on and check logs

```bash
ssh veerobot@ambulance-robot.local
sudo journalctl -fu v2x_ambulance
```

Expected log:
```
Camera: picamera2  320×240
Vision stream at http://<robot-ip>:5005/
V2X AMBULANCE ROBOT READY
[OBU] SESSION ESTABLISHED SUCCESSFULLY
```

> **The ambulance starts ARMED automatically** and begins lane following immediately once the camera sees the track. No Start button needed.

---

### STEP 5 — Verify on Dashboard

After both Pis connect, the Dashboard at `http://localhost:5000` should show:

| Field | Expected value |
|-------|---------------|
| ENTITIES | **3** — RSU + Car OBU + Ambulance OBU |
| SESSIONS ✓ | increments on each restart |
| TS FAILURES | 0 |
| AVG LATENCY | ~15 ms |

---

### Normal restart (keys already exist)

No key clearing needed. Just start in order:

```bash
# Laptop — Terminal 1:
cd ~/V2X/v2x_testbed/desktop && python3 server.py

# Laptop — Terminal 2:
cd ~/V2X/v2x_testbed/rsu/build && ./rsu_server ../config/rsu_config.json

# Car Pi:
sudo systemctl restart v2x_car

# Ambulance Pi:
sudo systemctl restart v2x_ambulance
```

---

## Viewing the Live Camera Stream

Every robot runs an MJPEG HTTP server on port **5005**. No extra software needed — just a browser.

### Open in browser

```
Car:       http://192.168.0.100:5005/
Ambulance: http://192.168.0.104:5005/
```

Replace the IPs with your actual Pi IPs. You can have both open in different browser tabs simultaneously.

### What you see

```
┌──────────────────────────────────────────────────────────────┐
│  Full camera frame (640 px wide)                             │
│  ─── yellow dashed line = crop boundary ────────────────── │
├──────────────────────────┬───────────────────────────────────┤
│  LANE overlay            │  HSV MASK                         │
│  green line  = centre    │  grey  = white pixels detected    │
│  orange line = target    │  yellow = yellow pixels detected  │
│  red dot = centroid      │  black  = nothing detected        │
├──────────────────────────┴───────────────────────────────────┤
│  zone=3  vx=0.20  wz=+0.05  NORMAL                          │
└──────────────────────────────────────────────────────────────┘
```

**Runs at ~10 fps** — sufficient for tuning without heavy network load.

### Using the stream for HSV calibration

Look at the **HSV MASK** panel (right side of middle row):
- If yellow lane lines are missing or faint → lower `yellow_s_low` or `yellow_v_low`
- If white marks are not showing → lower `white_v_low`
- If the black track floor leaks into the mask → raise the `_low` values back up
- If markings only show up partially → check lighting (shadows are the main enemy)

Edit `robot_python/config.yaml`, push, `git pull` on the Pi, `sudo systemctl restart v2x_car`.

### Find the Pi's IP address

```bash
# From laptop:
ping car-robot.local        # then check the IP in the reply
# OR on the Pi:
hostname -I
```

---

## Joystick Controls

| Input | Action |
|-------|--------|
| Press **Start** (btn 7) | **Arm** — robot begins autonomous lane following |
| Press **Start** again | **Disarm** — robot stops immediately |
| Hold **LB** (btn 4) | Override to manual joystick control (autonomous pauses) |
| Hold **LB + RB** (btn 4 + 5) | Turbo speed (0.8 m/s) |
| Left stick Y | Forward / reverse |
| Right stick X | Steer left / right |
| Release LB | Return to autonomous lane following |

> The **ambulance does not require arming** — it starts moving as soon as the service starts.  
> The **car starts disarmed** on every boot/restart. Always arm deliberately.  
> Run `jstest /dev/input/js0` on the Pi to verify button numbers match your controller. Edit `config.yaml` under `joystick:` if they differ.

---

## AprilTag Layout

The arena uses **18 AprilTag 36h11** markers (10 cm × 10 cm printed size):

| Group | IDs | Location | Purpose |
|-------|-----|----------|---------|
| **Inner oval** | **0 – 9** | Along the white oval boundary | Primary zone tracking — robot follows these |
| **Outer track** | **10 – 17** | Around the outer yellow boundary | Recovery reference — robot logs warning if seen |

**Tag placement rules:**
- Inner tags 0–9: place **in order** around the white oval, going in one consistent direction (clockwise or counterclockwise — pick one and stick to it)
- Outer tags 10–17: place anywhere on the outer yellow boundary — order does not matter
- All tags lie flat on the floor in the black boxes shown in `arena.svg`
- Spacing between inner tags: ~61 cm ground distance

**When the robot sees an outer tag** (ID 10–17), it logs:  
`Outer reference tag id=XX — robot off inner track`  
The last known inner zone is preserved, and the lane follower tries to bring the robot back.

---

## Testing the Emergency Chain

### Full test with both robots

1. Start everything (Steps 1–4 above), arm the car
2. Ambulance OBU authenticates with `is_emergency: true` → RSU broadcasts `EMERGENCY_ACTIVE` → car receives it
3. Car logs: `V2X emergency ACTIVE → YIELDING → EVADING → HOLDING`
4. Stop the ambulance: `sudo systemctl stop v2x_ambulance`
5. After ~5 s: car logs `Emergency cleared → RESUMING → NORMAL`

### Manual test — no ambulance robot needed

From the laptop (replace `192.168.0.100` with your car's IP):

```bash
python3 -c "
import socket, json, time
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.sendto(json.dumps({'type':'EMERGENCY_ACTIVE','session_id':'test-001'}).encode(),
         ('192.168.0.100', 5001))
print('Emergency sent — car should evade')
time.sleep(8)
s.sendto(json.dumps({'type':'EMERGENCY_CLEARED','session_id':'test-001'}).encode(),
         ('192.168.0.100', 5001))
print('Emergency cleared')
"
```

Expected car log sequence: `EVADING (2s) → HOLDING → RESUMING (2s ramp) → NORMAL`

### Manual emergency via control socket

```bash
# Activate emergency on car (triggers evasion without OBU/RSU)
python3 control_socket.py --port 5010 --host 192.168.0.100 emergency_on
python3 control_socket.py --port 5010 --host 192.168.0.100 emergency_off
```

---

## Multiple Robots — Can You Scale Up?

### Multiple cars — YES, works out of the box

Each car:
- Independently receives the RSU broadcast emergency alert on port 5001 → each car yields on its own
- Independently broadcasts its own position to the subnet
- Independently tracks the nearest ambulance zone
- Has its own vision stream on port 5005 (unique IP = no conflict)
- Has its own control socket on port 5010 (send to its specific IP)

No code changes needed. Add another car Pi → run `setup.sh car` → done.

### Multiple ambulances — YES, supported

The position broadcaster already handles multiple ambulances. When a car detects multiple ambulances, it yields to the one with the **highest zone number** (furthest along the track = closest behind it). Each ambulance independently sends `EMERGENCY_ACTIVE` via its own OBU → RSU → car.

### Multiple RSUs — PARTIAL

Multiple RSU binaries can run simultaneously if each has a unique entity ID and config. Since all alert to `192.168.0.255:5001`, cars receive from all of them. In practice one RSU is enough for a demo — the broadcast covers the whole subnet.

### Summary table

| Scenario | Supported | Notes |
|----------|-----------|-------|
| 1 car + 1 ambulance | ✓ Full | Default configuration |
| 2+ cars + 1 ambulance | ✓ Full | Each car yields independently |
| 1 car + 2+ ambulances | ✓ Full | Car yields to nearest (highest zone) |
| 2+ cars + 2+ ambulances | ✓ Full | Each car+ambulance pair self-organises |
| 2+ RSUs | ✓ Partial | Duplicate alerts are handled gracefully |

---

## Useful Commands

### Car Pi

```bash
# Service control
sudo systemctl start   v2x_car
sudo systemctl stop    v2x_car
sudo systemctl restart v2x_car          # use after config/code change
sudo journalctl -fu    v2x_car          # live log stream
sudo journalctl -u     v2x_car -n 100   # last 100 lines

# Run manually (for debugging — stop service first)
sudo systemctl stop v2x_car
cd ~/projects/V2X/robot_python && source .venv/bin/activate
python3 main_car.py --debug-image --debug-position   # opens local OpenCV windows

# Control socket (from laptop or same Pi)
python3 control_socket.py --port 5010 --host 192.168.0.100 arm
python3 control_socket.py --port 5010 --host 192.168.0.100 disarm
python3 control_socket.py --port 5010 --host 192.168.0.100 estop
python3 control_socket.py --port 5010 --host 192.168.0.100 status
python3 control_socket.py --port 5010 --host 192.168.0.100 emergency_on
python3 control_socket.py --port 5010 --host 192.168.0.100 emergency_off

# Hardware tests (stop service first)
python3 test_driver.py    # live telemetry
python3 motor_test.py     # drives forward 3 s
python3 diag_drive.py     # interactive drive + telemetry
```

### Ambulance Pi

```bash
sudo systemctl start   v2x_ambulance
sudo systemctl stop    v2x_ambulance
sudo systemctl restart v2x_ambulance
sudo journalctl -fu    v2x_ambulance

# Control socket (port 5011 for ambulance)
python3 control_socket.py --port 5011 --host 192.168.0.104 emergency_on
python3 control_socket.py --port 5011 --host 192.168.0.104 emergency_off
```

### Laptop

```bash
# Clear sessions before a demo
cd ~/V2X/v2x_testbed
rm -f database/v2x_testbed.db database/master_secret.bin
rm -rf rsu/build/keys/
# Also on each Pi: rm -rf ~/projects/V2X/robot_python/keys/

# Check NTP sync on Pi (KC1 fails if clocks are out of sync)
ssh veerobot@car-robot.local timedatectl status
# Must show: System clock synchronized: yes

# Camera snapshot (on Pi)
cd ~/projects/V2X/robot_python && source .venv/bin/activate
python3 -c "
import picamera2, time
cam = picamera2.Picamera2()
cam.configure(cam.create_video_configuration(main={'size':(320,240),'format':'BGR888'}))
cam.start(); time.sleep(2)
cam.capture_file('/tmp/snap.jpg')
cam.stop()
print('Saved /tmp/snap.jpg — scp to view it')
"
scp veerobot@car-robot.local:/tmp/snap.jpg .   # copy to laptop to view
```

---

## Key Config Files

All changes happen in the repo. Edit → commit → push → `git pull` on each Pi → `sudo systemctl restart`.

| File | What it controls |
|------|-----------------|
| `robot_python/config.yaml` | All robot settings — one file, role sections for car/ambulance |
| `v2x_testbed/obu/config/obu_local.json` | **gitignored** — generated by `setup.sh` per device |
| `v2x_testbed/obu/config/obu1_config.json` | RSU IP, Desktop IP (update when laptop IP changes) |
| `v2x_testbed/rsu/config/rsu_config.json` | Emergency broadcast target IP/port, timestamp tolerance |

### Critical values in config.yaml

```yaml
camera:
  width: 320
  height: 240
  use_picamera2: true    # ArduCam 8MP (IMX219) uses picamera2

lane_follower:
  crop_top_ratio: 0.40   # 30° tilt / 350mm height → sees 0.25–0.75m ahead
  linear_speed:   0.20   # m/s (car); ambulance overrides to 0.28

  # Tune these under your actual arena lighting using the browser stream:
  white_v_low:    190    # lower if white marks look grey → try 160
  yellow_h_low:    20    # shift if yellow looks orange or lime-green
  yellow_s_low:    80    # lower if yellow looks washed out

position:
  n_inner_tags:   10     # AprilTags IDs 0–9 on inner white oval
  n_outer_tags:    8     # AprilTags IDs 10–17 on outer track (recovery only)
  tag_spacing_m:  0.70   # 3D slant: sqrt(0.35m² + 0.61m²)
  tag_size_m:     0.10   # must match actual printed tag size
  focal_px:      264.0   # ArduCam 8MP IMX219 at 320px — recalibrate if needed

stream:
  enabled: true
  port: 5005             # browser: http://<robot-ip>:5005/

emergency_handler:
  n_tags:           10   # must match n_inner_tags
  yield_zone_gap:    3   # yield if ambulance ≤ 3 zones (~1.8 m) behind
  evasion_angular_speed: 0.9   # rad/s left turn — tune per track width
  evasion_duration_s:    2.0   # seconds of turning before holding
```

### focal_px calibration (do this once on track)

```bash
# On the Pi, with track built and a tag visible at a known distance:
cd ~/projects/V2X/robot_python && source .venv/bin/activate
python3 main_car.py --debug-position   # shows tag detection window (needs display or VNC)
# Hold a tag at exactly 0.40 m from the camera lens
# Read pixel_width from the OpenCV window
# focal_px = pixel_width × 0.40 / 0.10
# Update config.yaml and restart
```

---

## Git Workflow

**Car Pi is the source of truth.** Edit here, push, pull everywhere else.

```bash
# On Car Pi — after any change:
cd ~/projects/V2X
git add robot_python/config.yaml   # (or other changed files)
git commit -m "description"
git push origin main

# On Laptop and Ambulance Pi — to get latest:
cd ~/V2X && git pull          # laptop path
cd ~/projects/V2X && git pull  # Pi path
sudo systemctl restart v2x_car         # apply on car
sudo systemctl restart v2x_ambulance   # apply on ambulance
```

---

## Adding a New Robot

1. Flash Ubuntu 24.04, set unique hostname (`v2x-car2`, `v2x-emgy2`, etc.), enable SSH
2. `git clone https://github.com/VEEROBOT/V2X.git ~/projects/V2X`
3. Set the laptop IP in the OBU config:
   ```bash
   nano ~/projects/V2X/v2x_testbed/obu/config/obu1_config.json
   # set "rsu_ip" and "desktop_ip" to your laptop's WiFi IP
   ```
4. Run setup:
   ```bash
   sudo bash ~/projects/V2X/robot_python/setup.sh car       # or: ambulance
   sudo reboot
   ```

`setup.sh` generates `obu_local.json` automatically (unique entity_id from hostname, correct `is_emergency` flag). No other manual edits needed.

---

## Port Reference

| Port | Protocol | Direction | Purpose |
|------|----------|-----------|---------|
| 5000 | UDP | OBU → RSU | V2X authentication |
| 5000 | HTTP | Browser → Laptop | Dashboard UI |
| 5001 | UDP | RSU → all robots (broadcast) | Emergency alert (ACTIVE / CLEARED) |
| 5002 | UDP | Car ↔ Ambulance (broadcast) | Position sharing |
| 5003 | UDP | OBU listen | OBU receive port |
| **5005** | **HTTP** | **Browser → Robot** | **Live vision stream (new)** |
| 5010 | UDP | Any → Car | Car control socket (arm/disarm/emergency) |
| 5011 | UDP | Any → Ambulance | Ambulance control socket |
| 8001 | TCP | OBU → Laptop | OBU entity registration |
| 8002 | TCP | RSU → Laptop | RSU entity registration |
| 9000 | TCP | RSU → Laptop | Audit log stream |

---

## Troubleshooting

### Robot does not move after boot (car)

Normal — the car starts **disarmed**. Press **Start** (btn 7) to arm.  
Or arm remotely:
```bash
python3 control_socket.py --port 5010 --host 192.168.0.100 arm
```

### Cannot see the browser stream at http://robot-ip:5005/

```bash
# Check stream is running:
ssh veerobot@car-robot.local
sudo journalctl -u v2x_car | grep "Vision stream"
# Should show: Vision stream at http://<ip>:5005/

# Check port is open:
ss -tlnp | grep 5005

# Check config:
grep -A3 "^stream:" ~/projects/V2X/robot_python/config.yaml
# Must show: enabled: true
```
If `enabled: false`, edit config.yaml, commit, pull on Pi, restart service.

### Lane marks not detected (mask panel is mostly black)

- Lower `white_v_low` from 190 → 160 (white marks may look grey under your lights)
- Lower `yellow_s_low` from 80 → 60 (yellow may look washed out)
- Check lighting — avoid direct sunlight or deep shadows across the track
- Verify crop line is in the right place — if the yellow dashed line in the stream is too high or low, adjust `crop_top_ratio`

### KC1 verify fail

RSU re-registered but OBU has the old RSU public key.  
**Rule: if you clear RSU keys, clear OBU keys on ALL Pis.**
```bash
rm -rf ~/projects/V2X/robot_python/keys/
sudo systemctl restart v2x_car
```

### KC2 timeout

Stale session in RSU database. Full clear on laptop:
```bash
cd ~/V2X/v2x_testbed
rm -f database/v2x_testbed.db database/master_secret.bin
rm -rf rsu/build/keys/
```
Clear OBU keys on each Pi. Follow Fresh Start sequence (Step 0 → 1 → 2 → 3 → 4).

### ENTITIES = 0 on Dashboard

Wrong start order. Always: Desktop → RSU → Pis.
```bash
# Clear and restart:
rm -rf ~/V2X/v2x_testbed/rsu/build/keys/
# Clear each Pi: rm -rf ~/projects/V2X/robot_python/keys/
# Then: Desktop → RSU → Pis
```

### TIMESTAMP_CHECK_FAIL

Laptop clock is out of sync with Pi, or `delta_ts_ms` is too tight.
```bash
# On laptop:
cd ~/V2X && git pull   # confirm rsu_config.json has delta_ts_ms: 500
# Restart RSU
```

### RSU alert not received (car never evades)

```bash
sudo journalctl -u v2x_car | grep "RSU alert listener"
# Must show: RSU alert listener started on UDP port 5001
```
- Check `v2x_bridge: manual_mode: false` in `config.yaml`
- Check Pi and laptop are on the **same WiFi subnet** (both on `192.168.0.x`)
- Check RSU config has `"car_alert_ip": "192.168.0.255"` (broadcast, not a specific IP)

### Camera not working

```bash
# Test directly (stop service first):
sudo systemctl stop v2x_car
cd ~/projects/V2X/robot_python && source .venv/bin/activate
python3 -c "import picamera2; c=picamera2.Picamera2(); print(c.camera_properties)"
# Should print sensor info — if it errors, see below
```
- Ribbon cable must be in **CAM/DISP 0** port (not port 1)
- `dmesg | grep imx219` — should show `registered`
- Re-run `sudo bash setup.sh car` if libcamera was not fully built

### STM32 not responding

```bash
ls -la /dev/ttyRobot       # must exist (symlink to ttyAMA10 on RPi 5)
groups                     # must include: dialout
python3 test_driver.py     # should show telemetry
```
If `/dev/ttyRobot` is missing:
```bash
echo 'KERNEL=="ttyAMA10", SYMLINK+="ttyRobot"' | sudo tee /etc/udev/rules.d/99-uart-v2x.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```
If telemetry shows loopback (reads its own transmit): **unplug the STM32 USB cable from the Pi** — when USB is connected, STM32 routes UART to USB and the Pi sees its own bytes back.

### Joystick not detected

USB receiver takes ~5 s to enumerate. The joystick thread retries automatically. Wait 10 s after boot. Check:
```bash
ls /dev/input/js0
jstest /dev/input/js0
```
If missing, unplug and re-plug the USB dongle.

### Known quirks

- **Battery voltage ~4.7V in logs** — normal. STM32 reads its internal ADC reference, not the actual battery. Ignore.
- **Keys must be cleared together** — if RSU re-registers, OBU must re-register or KC1/KC2 will fail.
- **STM32 USB must be unplugged** during normal operation — USB overrides UART on the STM32 board.
- **RPi 5 older kernels (≤6.8.0-1031)** expose internal RP1 UART as `/dev/ttyAMA0` with hardware loopback — fixed by using `/dev/ttyRobot` (setup.sh handles this).
