# Working With V2X — Complete Operations Guide

> Last updated: 2026-06-14
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
8. [Diagnostic Commands](#diagnostic-commands)
9. [Multiple Robots — Can You Scale Up?](#multiple-robots--can-you-scale-up)
10. [Useful Commands](#useful-commands)
11. [Key Config Files](#key-config-files)
12. [Git Workflow](#git-workflow)
13. [Adding a New Robot](#adding-a-new-robot)
14. [Port Reference](#port-reference)
15. [Configurable Modes (Advanced)](#configurable-modes-advanced)
16. [Troubleshooting](#troubleshooting)

---

## What Runs Where

```
LAPTOP  (e.g. 192.168.0.103)
  ├── Desktop server    ~/V2X/v2x_testbed/v2x_run_desktop.sh  → Dashboard http://localhost:5000
  └── RSU binary        ~/V2X/v2x_testbed/v2x_run_rsu.sh
        ├── UDP 5000  ← OBU authentication
        ├── TCP 8001  ← OBU entity registration
        ├── TCP 8002  ← RSU entity registration
        ├── TCP 9000  ← audit log from RSU
        └── UDP 5001 broadcast → EMERGENCY_ACTIVE / EMERGENCY_CLEARED to all robots

CAR PI  (hostname: v2x, e.g. 192.168.0.100)
  └── systemd: v2x_car → main_car.py        starts DISARMED — press Start to arm
        ├── Camera (ArduCam 8MP, picamera2, 320×240)
        ├── STM32 motor controller  /dev/ttyRobot
        ├── Joystick  /dev/input/js0  (auto-detects, retries every 5 s)
        ├── Lane follower + AprilTag position estimator
        ├── OBU client  (authenticates every ~30 s)
        ├── RSU alert listener  UDP 5001 ← receives EMERGENCY_ACTIVE
        ├── Position broadcaster  UDP 5002 ↔ ambulance
        └── Vision stream  http://car-ip:5005/

AMBULANCE PI  (hostname: v2x-emgy, e.g. 192.168.0.104)
  └── systemd: v2x_ambulance → main_ambulance.py   starts DISARMED — press Start to arm
        ├── Camera, STM32, Joystick  (same as car)
        ├── Lane follower + AprilTag position estimator
        ├── OBU client  (loops every ~2 s — keeps emergency flag active)
        ├── Position broadcaster  UDP 5002 ↔ car
        └── Vision stream  http://ambulance-ip:5005/
```

---

## Network Layout

| Device | IP (example) | Hostname | What it runs |
|--------|-------------|----------|--------------|
| Laptop | `192.168.0.103` | `v2x` (dev) | RSU binary + Desktop server |
| Car Pi | `192.168.0.100` | `v2x` | `v2x_car` systemd service |
| Ambulance Pi | `192.168.0.104` | `v2x-emgy` | `v2x_ambulance` systemd service |

All devices must be on the same WiFi network. The RSU broadcasts emergency alerts to `192.168.0.255` (subnet broadcast) — every robot receives them automatically.

---

## Step-by-Step Activation

### Order matters: Desktop → RSU → Pis

The Desktop distributes public keys. RSU must register with Desktop **before** any OBU does, so it must start second. Each script handles its own cleanup automatically.

---

### STEP 1 — Laptop: start the Desktop server (Terminal 1)

```bash
~/V2X/v2x_testbed/v2x_run_desktop.sh
```

This clears the database and RSU keys, then starts the Flask server.

Expected output:
```
[v2x] Clearing sessions and RSU keys...
[v2x] Starting Desktop server...
[DASH] Dashboard starting on http://localhost:5000
```

Open `http://localhost:5000` in a browser. Leave this terminal running.

---

### STEP 2 — Laptop: start the RSU (Terminal 2)

```bash
~/V2X/v2x_testbed/v2x_run_rsu.sh
```

This clears old RSU keys and starts the RSU binary. The RSU re-registers with Desktop and receives a fresh keypair.

Expected output:
```
[v2x] Clearing RSU keys...
[v2x] Starting RSU...
[REG] ✓ Registration complete for RSU
[UDP] Listening on 0.0.0.0:5000
```

Dashboard shows: **ENTITIES = 1 (RSU)**. Leave this terminal running.

---

### STEP 3 — Car Pi: fresh start

On the Car Pi:
```bash
v2x_run_car
```

This regenerates `obu_local.json` with the correct entity ID and clears old OBU keys, then restarts the service and tails the log.

Expected log:
```
[v2x] Regenerating OBU config: entity_id=V2X  is_emergency=false
[v2x] Clearing OBU keys...
[v2x] Restarting v2x_car...
Camera: picamera2  320×240
Joystick: 'Xbox 360 Controller'  deadman=btn4  turbo=btn5  arm=btn7
V2X CAR ROBOT READY
[OBU] SESSION ESTABLISHED SUCCESSFULLY
```

> **The car starts DISARMED.** Motors will not move until you arm it.
> **To arm:** press the **Start button (btn 7)** on the joystick.
> **To arm remotely** (no joystick):
> ```bash
> python3 ~/projects/V2X/robot_python/control_socket.py --port 5010 --host 192.168.0.100 arm
> ```

Dashboard shows: **ENTITIES = 2 (RSU + V2X)**

---

### STEP 4 — Ambulance Pi: fresh start

On the Ambulance Pi:
```bash
v2x_run_ambulance
```

Expected log:
```
[v2x] Regenerating OBU config: entity_id=V2X_EMGY  is_emergency=true
[OBU] [UDP] Bound to 0.0.0.0:0  ← OS assigns ephemeral port
V2X AMBULANCE ROBOT READY
[OBU] SESSION ESTABLISHED SUCCESSFULLY
🚑 Emergency priority flag sent
```

> **The ambulance also starts DISARMED.** Press **Start (btn 7)** to arm and begin lane following.
> Press **A button** to activate the V2X emergency signal; **B button** to cancel it.

Dashboard shows: **ENTITIES = 3 (RSU + V2X + V2X_EMGY)**, EMERGENCY_PRIORITY_GRANTED events start appearing.

---

### STEP 5 — Verify on Dashboard

After both Pis connect, `http://localhost:5000` should show:

| Field | Expected |
|-------|---------|
| ENTITIES | **3** — RSU, V2X (car), V2X_EMGY (ambulance) |
| ONLINE status | Green dot ● next to car and ambulance; grey ● = OFFLINE |
| Emergency column | 🚑 Yes for V2X_EMGY, No for car and RSU |
| EVENT COUNTS | SESSION_ESTABLISHED incrementing, no failures |
| EMERGENCY PRIORITY GRANTS | counting up (ambulance re-auths every ~2 s) |
| AVG LATENCY | ~8–15 ms |

The entity table updates live via WebSocket — no page refresh needed. If a robot's battery dies or crashes, the dashboard marks it OFFLINE automatically within ~50 s (heartbeat watchdog).

Or check from the command line:
```bash
~/V2X/v2x_testbed/v2x_status.sh
```

---

### Normal restart (no key changes needed)

Use the run scripts — they always regenerate configs and clear keys:

```bash
# Laptop Terminal 1:
~/V2X/v2x_testbed/v2x_run_desktop.sh

# Laptop Terminal 2:
~/V2X/v2x_testbed/v2x_run_rsu.sh

# Car Pi:
v2x_run_car

# Ambulance Pi:
v2x_run_ambulance
```

> If you only changed `config.yaml` (not crypto config), you can use `sudo systemctl restart v2x_car` / `sudo systemctl restart v2x_ambulance` without regenerating keys. Use `v2x_run_*` scripts whenever you want a clean auth slate.

---

## Viewing the Live Camera Stream

Every robot runs an MJPEG HTTP server on port **5005**. Open in any browser — no extra software needed.

```
Car:       http://192.168.0.100:5005/
Ambulance: http://192.168.0.104:5005/
```

Both can be open in different tabs simultaneously. The browser tab title shows the robot name (e.g. `V2X_CAR_01 | Robot Vision`).

### What you see

```
┌─ V2X_CAR_01 ────────────────────────────── 23:14:05 ────────┐
│  Full camera frame (640 px wide)                             │
│  ─── yellow dashed line = crop boundary ───────────────────  │
├──────────────────────┬───────────────────────────────────────┤
│  LANE overlay        │  HSV MASK                             │
│  green = centre      │  grey  = white pixels detected        │
│  orange = target     │  yellow = yellow pixels detected      │
│  red dot = centroid  │  black  = nothing                     │
├──────────────────────┴───────────────────────────────────────┤
│  CAR zone=3  AMB zone=7  vx=0.20  wz=+0.05  NORMAL          │
│  ARMED  AUTO  V2X:ACTIVE  BAT:7.4V  PI:52.3C                │
└──────────────────────────────────────────────────────────────┘
```

- **Robot name** — top-left corner of frame, white text with black outline
- **Time** — top-right corner (uses Pi system clock — set timezone with `sudo timedatectl set-timezone Asia/Kolkata`)
- **BAT:X.XV** — battery voltage from STM32 ADC (accurate once voltage divider is wired)
- **PI:XX.XC** — Pi CPU temperature live from sysfs

### HSV calibration via stream

Look at the **HSV MASK** panel:
- White marks missing → lower `white_v_low` (try 160 instead of 190)
- Yellow marks faint → lower `yellow_s_low` (try 60 instead of 80)
- Floor leaking in → raise the `_low` values back up
- Marks only partially visible → check lighting (shadows are the main enemy)

Edit `robot_python/config.yaml`, commit, `git pull` on the Pi, `sudo systemctl restart v2x_car`.

---

## Joystick Controls

| Input | Car | Ambulance |
|-------|-----|-----------|
| Press **Start** (btn 7) | Arm / Disarm toggle | Arm / Disarm toggle |
| Hold **LB** (btn 4) | Manual override (joystick drives) | Manual override |
| Hold **LB + RB** (btn 4+5) | Turbo (0.8 m/s) | Turbo (0.8 m/s) |
| Left stick Y | Forward / reverse | Forward / reverse |
| Right stick X | Steer | Steer |
| **A button** | — | Activate V2X emergency signal (test without OBU) |
| **B button** | — | Cancel V2X emergency signal |
| **X button** | Record training path | Record training path |
| **Mode button** (btn 8) | Toggle OBU service on/off → ONLINE/OFFLINE on dashboard | Toggle OBU service on/off |
| Release LB | Return to autonomous | Return to autonomous |

> Both robots start **DISARMED** on every boot/restart. Always arm deliberately.
> The joystick is detected automatically — wait ~10 s after boot if it wasn't plugged in first.
> Run `jstest /dev/input/js0` to verify button numbers match your controller.
> **Mode button** is handled by `v2x_obu_trigger.service` (runs as root, separate from the main robot service). Press once to start V2X; press again to stop. The dashboard shows the entity going ONLINE/OFFLINE in real time. If Mode does nothing, check: `sudo systemctl status v2x_obu_trigger`.

---

## AprilTag Layout

The arena uses **18 AprilTag 36h11** markers (10 cm × 10 cm printed size):

| Group | IDs | Location | Purpose |
|-------|-----|----------|---------|
| **Inner oval** | **0 – 9** | Along the white oval boundary | Primary zone tracking |
| **Outer track** | **10 – 17** | Around the outer yellow boundary | Recovery reference |

**Tag placement rules:**
- Inner tags 0–9: place in order around the white oval, clockwise (viewed from above)
- Outer tags 10–17: anywhere on outer yellow boundary, order does not matter
- All tags flat on floor, 10 cm × 10 cm
- Spacing between inner tags: ~61 cm

When the robot sees an outer tag (ID 10–17) it logs:
`Outer reference tag id=XX — robot off inner track`
and tries to return to the inner oval.

---

## Testing the Emergency Chain

### Full test with both robots

1. Start everything (Steps 1–4), arm both robots
2. On the ambulance: press **A** to activate the emergency signal
3. Ambulance OBU authenticates with `is_emergency: true` → RSU broadcasts `EMERGENCY_ACTIVE` → car receives it
4. Car logs: `V2X emergency ACTIVE → EVADING → HOLDING`
5. Press **B** on ambulance to cancel, or stop the service: `sudo systemctl stop v2x_ambulance`
6. After ~5 s: car logs `Emergency cleared → RESUMING → NORMAL`

### Manual test — no ambulance robot needed

From the laptop (replace IP with your car's IP):

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

Expected car sequence: `EVADING (2 s) → HOLDING → RESUMING (2 s ramp) → NORMAL`

---

## Diagnostic Commands

### System health summary (laptop)

```bash
~/V2X/v2x_testbed/v2x_status.sh
# Save to file:
~/V2X/v2x_testbed/v2x_status.sh > ~/v2x_status.txt
```

Shows: entities registered, event counts, recent errors, session latency.

### Robot log snapshot (on each Pi)

```bash
v2x_robot_log              # auto-detects car or ambulance
v2x_robot_log > ~/v2x_log.txt   # save to file for sharing
```

Shows: service status, startup events, recent OBU events, errors, current OBU config.

### Quick health checks

```bash
# Are all 3 entities registered?
~/V2X/v2x_testbed/v2x_status.sh | grep ENTITIES

# Any failures?
~/V2X/v2x_testbed/v2x_status.sh | grep "FAIL\|No failures"

# Is ambulance getting EMERGENCY_PRIORITY_GRANTED?
~/V2X/v2x_testbed/v2x_status.sh | grep EMERGENCY
```

---

## Multiple Robots — Can You Scale Up?

### Multiple cars — YES

Each car independently receives RSU broadcast alerts on port 5001 and yields autonomously. Add another car Pi → `setup.sh car` → done.

### Multiple ambulances — YES

Each ambulance independently sends `EMERGENCY_ACTIVE` via its own OBU. When a car detects multiple ambulances, it yields to the one with the highest zone number (closest behind it on track).

### Summary table

| Scenario | Supported |
|----------|-----------|
| 1 car + 1 ambulance | ✓ Full |
| 2+ cars + 1 ambulance | ✓ Full |
| 1 car + 2+ ambulances | ✓ Full |
| 2+ cars + 2+ ambulances | ✓ Full |

---

## Useful Commands

### On the Car Pi

```bash
# Fresh start (regenerates OBU config + keys, restarts service, tails log)
v2x_run_car

# Service control
sudo systemctl restart v2x_car      # quick restart (keeps existing keys)
sudo systemctl stop    v2x_car
sudo journalctl -fu    v2x_car      # live log
sudo journalctl -u     v2x_car -n 100  # last 100 lines

# Robot log snapshot
v2x_robot_log > ~/v2x_log.txt

# Control socket (from laptop or same Pi)
python3 ~/projects/V2X/robot_python/control_socket.py --port 5010 --host 192.168.0.100 arm
python3 ~/projects/V2X/robot_python/control_socket.py --port 5010 --host 192.168.0.100 disarm
python3 ~/projects/V2X/robot_python/control_socket.py --port 5010 --host 192.168.0.100 estop
python3 ~/projects/V2X/robot_python/control_socket.py --port 5010 --host 192.168.0.100 status
python3 ~/projects/V2X/robot_python/control_socket.py --port 5010 --host 192.168.0.100 emergency_on
python3 ~/projects/V2X/robot_python/control_socket.py --port 5010 --host 192.168.0.100 emergency_off

# Hardware tests (stop service first)
cd ~/projects/V2X/robot_python && source .venv/bin/activate
python3 motor_test.py    # drives forward 3 s to verify wheels
python3 diag_drive.py    # interactive drive + live telemetry
```

### On the Ambulance Pi

```bash
# Fresh start
v2x_run_ambulance

# Service control
sudo systemctl restart v2x_ambulance
sudo systemctl stop    v2x_ambulance
sudo journalctl -fu    v2x_ambulance

# Robot log snapshot
v2x_robot_log > ~/v2x_log.txt

# Control socket (port 5011)
python3 ~/projects/V2X/robot_python/control_socket.py --port 5011 --host 192.168.0.104 arm
python3 ~/projects/V2X/robot_python/control_socket.py --port 5011 --host 192.168.0.104 disarm
python3 ~/projects/V2X/robot_python/control_socket.py --port 5011 --host 192.168.0.104 emergency_on
python3 ~/projects/V2X/robot_python/control_socket.py --port 5011 --host 192.168.0.104 emergency_off
```

### On the Laptop

```bash
# System status
~/V2X/v2x_testbed/v2x_status.sh

# Start everything fresh
~/V2X/v2x_testbed/v2x_run_desktop.sh   # Terminal 1
~/V2X/v2x_testbed/v2x_run_rsu.sh       # Terminal 2

# Check NTP sync on Pi (auth timestamps fail if clocks are out of sync)
ssh veerobot@v2x.local timedatectl status
# Must show: System clock synchronized: yes

# Camera snapshot (on Pi, view on laptop)
ssh veerobot@v2x.local \
  "cd ~/projects/V2X/robot_python && source .venv/bin/activate && python3 -c \"
import picamera2, time
cam = picamera2.Picamera2()
cam.configure(cam.create_video_configuration(main={'size':(320,240),'format':'BGR888'}))
cam.start(); time.sleep(2); cam.capture_file('/tmp/snap.jpg'); cam.stop()
print('Saved /tmp/snap.jpg')
\""
scp veerobot@v2x.local:/tmp/snap.jpg .
```

---

## Key Config Files

All changes happen in the repo. Edit → commit → push → `git pull` on each Pi → restart service.

| File | What it controls |
|------|-----------------|
| `robot_python/config.yaml` | All robot settings — HSV tuning, speed, joystick, algorithm |
| `v2x_testbed/obu/config/obu1_config.json` | RSU IP, Desktop IP — **update when laptop IP changes** |
| `v2x_testbed/obu/config/obu_local.json` | **gitignored** — auto-generated by `v2x_run_car` / `v2x_run_ambulance` |
| `v2x_testbed/rsu/config/rsu_config.json` | Emergency broadcast target, timestamp tolerance |

> `obu_local.json` is never edited manually. The run scripts regenerate it from `obu1_config.json`
> each time. If you change laptop IP, update `obu1_config.json`, commit, pull on Pis, run `v2x_run_*`.

### When laptop IP changes

```bash
# On a Pi (or laptop, then push):
nano ~/projects/V2X/v2x_testbed/obu/config/obu1_config.json
# Update: "rsu_ip" and "desktop_ip" to the new laptop IP
git commit -am "update laptop IP to 192.168.x.x"
git push

# On each Pi:
git pull && v2x_run_car        # or v2x_run_ambulance
```

### Critical values in config.yaml

```yaml
camera:
  width: 320
  height: 240
  use_picamera2: true

lane_follower:
  crop_top_ratio: 0.40
  linear_speed:   0.20   # m/s (car); ambulance uses 0.18 m/s

  # Tune these under your arena lighting using the browser stream:
  white_v_low:    190    # lower if white marks look grey → try 160
  yellow_h_low:    20
  yellow_s_low:    80    # lower if yellow looks washed out → try 60

position:
  n_inner_tags:   10
  n_outer_tags:    8
  tag_spacing_m:  0.70
  tag_size_m:     0.10
  focal_px:      264.0   # recalibrate if camera changes

stream:
  enabled: true
  port: 5005

emergency_handler:
  n_tags:           10
  yield_zone_gap:    3   # yield if ambulance ≤ 3 zones behind
  evasion_angular_speed: 0.9
  evasion_duration_s:    2.0
```

---

## Git Workflow

**Pi is source of truth.** Make changes on the Pi, push to GitHub, pull everywhere else. Never edit directly on the laptop unless it is a documentation-only change.

```bash
# On a Pi — after any change:
cd ~/projects/V2X
git add robot_python/config.yaml   # stage specific files
git commit -m "description of change"
git push origin main

# On laptop:
cd ~/V2X && git pull

# On other Pi:
cd ~/projects/V2X && git pull
sudo systemctl restart v2x_car         # or v2x_ambulance
```

---

## Adding a New Robot

1. Flash Ubuntu 24.04, set a unique hostname (e.g. `v2x-car2`), enable SSH
2. Clone the repo:
   ```bash
   git clone https://github.com/VEEROBOT/V2X.git ~/projects/V2X
   ```
3. Set the laptop IP in the OBU config (this is the only manual edit):
   ```bash
   nano ~/projects/V2X/v2x_testbed/obu/config/obu1_config.json
   # Set "rsu_ip" and "desktop_ip" to your laptop's WiFi IP
   ```
4. Run setup:
   ```bash
   sudo bash ~/projects/V2X/robot_python/setup.sh car       # or: ambulance
   sudo reboot
   ```

After reboot, the service starts automatically. Run `v2x_run_car` (or `v2x_run_ambulance`) for a clean auth start. The entity ID is derived from the hostname automatically — no other config needed.

---

## Port Reference

| Port | Protocol | Direction | Purpose |
|------|----------|-----------|---------|
| 5000 | UDP | OBU → RSU | V2X authentication |
| 5000 | HTTP | Browser → Laptop | Dashboard UI |
| 5001 | UDP | RSU → all robots (broadcast) | Emergency alert (ACTIVE / CLEARED) |
| 5002 | UDP | Car ↔ Ambulance | Position sharing |
| 5003 | UDP | Car OBU listen | Car OBU receive port (fixed) |
| `0`→ephemeral | UDP | Ambulance OBU | Ambulance OBU port (OS-assigned each restart) |
| 5005 | HTTP | Browser → Robot | Live vision stream |
| 5010 | UDP | Any → Car | Car control socket (arm/disarm/emergency) |
| 5011 | UDP | Any → Ambulance | Ambulance control socket |
| 8001 | TCP | OBU → Laptop | OBU entity registration |
| 8002 | TCP | RSU → Laptop | RSU entity registration |
| 9000 | TCP | RSU → Laptop | Audit log stream |

> The ambulance uses `udp_listen_port: 0` (OS assigns a fresh ephemeral port each restart). This prevents RSU session lookup collisions when the ambulance re-authenticates every 2 seconds.

---

## Configurable Modes (Advanced)

Two behaviours that were hardcoded are now selectable in `config.yaml`.
Both default to the original behaviour — flip one word to enable the new mode.

---

### RECOVERING exit mode

Controls how the car decides it has arced far enough back to the white line after yielding.

**`recovery_exit_mode: timer`** (default)
Exit after `recovery_duration_s: 3.5` seconds. Simple, always works.

**`recovery_exit_mode: gyro`**
Exit when the STM32 IMU measures `recovery_target_deg: 30.0` degrees of rotation.
Timer still fires as a safety net if gyro data is absent or unreliable.

```yaml
# robot_python/config.yaml — emergency_handler section
recovery_exit_mode: gyro      # timer | gyro
recovery_target_deg: 30.0     # degrees of yaw to accumulate before exiting
gyro_max_rad_s: 4.0           # spike filter — discard |gyro_z| above this (motor EMI)
gyro_min_samples: 3           # min valid readings before trusting the accumulation
```

**IMU note:** the IMU (LSM6DSRTR) is mounted inside the aluminium chassis close to the motors.
Motor switching creates EMI spikes that can reach 10+ rad/s. The spike filter (`gyro_max_rad_s`)
and minimum-samples guard (`gyro_min_samples`) protect against this. If the gyro data is too
noisy the mode silently falls back to the timer — it never gets stuck.

**How to test:**
1. Set `recovery_exit_mode: gyro` in config.yaml
2. Run `python3 main_car.py`, arm the robot, press **A** (simulate ambulance arrive)
3. Watch the log — you should see one of:
   ```
   RECOVERING → RESUMING: gyro 30.2° reached (47 samples)   ← gyro worked
   RECOVERING → RESUMING: gyro fallback — timer fired        ← IMU noise, fell back
   ```
4. Tune `recovery_target_deg` if the robot exits too early (raise it) or overshoots the white line (lower it).

---

### Dead-reckoning position

Controls how `distance_m` (distance within the current zone) is computed between AprilTag sightings.

**`position_mode: tag_only`** (default)
`distance_m` only updates when a tag is detected. Frozen between sightings.

**`position_mode: dead_reckoning`**
`distance_m` is integrated continuously from wheel encoder ticks.
Formula: `Δticks × (2π × 0.065 / 3600)` — no time dependency, purely event-driven.
Resets to zero every time an AprilTag is detected (ground truth always wins).

```yaml
# robot_python/config.yaml — position section
position_mode: dead_reckoning   # tag_only | dead_reckoning
ticks_per_rev: 3600             # from STM32 robot_config.h: 900 CPR × 4 (quadrature X4)
```

**Where 3600 comes from:**
```
ENC_RESOLUTION_CPR = 900    (encoder cycles per wheel revolution — through gearbox, calibrated by hand)
ENCODER_TICKS_REV  = 900 × 4 = 3600   (quadrature X4 mode sees both edges of both channels)
DISTANCE_PER_TICK  = π × 0.13 / 3600  ≈ 0.1135 mm per tick
```
This is defined in `STM32F405RGTx/Core/Inc/config/robot_config.h` and verified by manually
rotating the wheel one full turn and counting ticks (~±3600 measured).

**How to test:**
1. Set `position_mode: dead_reckoning` in config.yaml
2. Run `python3 main_car.py` with `logging.run_log: true`
3. Drive the robot between two AprilTags and watch `~/v2x_run.csv`:
   - In `tag_only` mode `distance_m` would stay frozen between tag detections
   - In `dead_reckoning` mode it should increase steadily, then snap to 0 when the next tag appears
4. If `distance_m` grows too fast or too slow, recheck `ticks_per_rev` by rotating one wheel by hand and reading `wheel_ticks` from the telemetry log.

---

## Troubleshooting

### Robot does not move after boot

Both robots start **disarmed**. Press **Start** (btn 7) to arm.
Or arm remotely:
```bash
python3 ~/projects/V2X/robot_python/control_socket.py --port 5010 --host 192.168.0.100 arm
```

### Joystick not detected at boot

The joystick thread retries every 5 seconds. Wait ~10 s after boot. If still missing:
```bash
ls /dev/input/js0
jstest /dev/input/js0
```
Unplug and re-plug the USB dongle if `/dev/input/js0` is absent.

### ENTITIES = 1 or 2 on Dashboard (OBU missing)

The OBU needs the RSU's public key to authenticate. The RSU must register with Desktop **before** OBUs start.

```bash
# On laptop, restart in correct order:
~/V2X/v2x_testbed/v2x_run_desktop.sh   # Terminal 1
~/V2X/v2x_testbed/v2x_run_rsu.sh       # Terminal 2 — wait for "[REG] ✓ Registration complete for RSU"
# Then run v2x_run_car / v2x_run_ambulance on the Pis
```

Look for `PUBLIC_KEY_PEER: 70 bytes` in the OBU log — this means it received the RSU's key.
`PUBLIC_KEY_PEER: 1 bytes` means 0 peers (RSU didn't register first).

### POST_AUTH_HMAC_FAIL in dashboard

Stale RSU session being reused. This means either:
- RSU has old keys from a previous run (fixed: `v2x_run_rsu.sh` now clears keys on every start)
- OBU is using an old config with `udp_listen_port: 5003` instead of `0` (ambulance only)

Fix:
```bash
# On ambulance Pi:
sudo chown veerobot:veerobot ~/projects/V2X/v2x_testbed/obu/config/obu_local.json
v2x_run_ambulance

# Check config shows udp_listen_port: 0:
v2x_robot_log | grep udp_listen_port
```

Then on laptop: `~/V2X/v2x_testbed/v2x_run_desktop.sh` + `v2x_run_rsu.sh` to get a clean slate.

### Cannot see browser stream at http://robot-ip:5005/

```bash
ssh veerobot@v2x.local
sudo journalctl -u v2x_car | grep "Vision stream"
# Must show: Vision stream at http://<ip>:5005/

# Check port is listening:
ss -tlnp | grep 5005
```
If not showing: check `stream: enabled: true` in `config.yaml`.

### Lane marks not detected (mask panel black)

- Lower `white_v_low` from 190 → 160 (white marks look grey under dim lighting)
- Lower `yellow_s_low` from 80 → 60 (yellow looks washed out)
- Check lighting — avoid direct sunlight or deep shadows across the track
- If crop line is in the wrong spot, adjust `crop_top_ratio` in config.yaml

### RSU alert not received (car never evades)

```bash
sudo journalctl -u v2x_car | grep "RSU alert listener"
# Must show: RSU alert listener started on UDP port 5001
```
- Check `v2x_bridge: manual_mode: false` in `config.yaml`
- Both Pi and laptop must be on the **same WiFi subnet** (both `192.168.0.x`)
- RSU config must have `"car_alert_ip": "192.168.0.255"` (broadcast, not a specific IP)

### TIMESTAMP_CHECK_FAIL events

Laptop clock out of sync with Pi, or delta too tight.
```bash
# On Pi:
timedatectl status   # must show: System clock synchronized: yes
sudo systemctl restart systemd-timesyncd  # force NTP sync
```
`delta_ts_ms` in `rsu_config.json` is set to 500 ms — do not reduce this.

### Camera not working

```bash
# Stop service, test directly:
sudo systemctl stop v2x_car
cd ~/projects/V2X/robot_python && source .venv/bin/activate
python3 -c "import picamera2; c=picamera2.Picamera2(); print(c.camera_properties)"
# Should print sensor info
```
- Ribbon cable must be in **CAM/DISP 0** port (not port 1)
- `dmesg | grep imx219` — should show `registered`
- Re-run `sudo bash setup.sh car` if libcamera was not fully built

### STM32 not responding

```bash
ls -la /dev/ttyRobot      # must exist (symlink to ttyAMA10 on RPi 5)
groups                    # must include: dialout
cd ~/projects/V2X/robot_python && source .venv/bin/activate
python3 motor_test.py     # drives forward 3 s
```

If `/dev/ttyRobot` is missing:
```bash
echo 'KERNEL=="ttyAMA10", SYMLINK+="ttyRobot"' | sudo tee /etc/udev/rules.d/99-uart-v2x.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

**If telemetry shows loopback** (Pi reads its own bytes back): unplug the STM32 USB cable — when USB is connected, STM32 routes UART to USB and Pi sees its own TX.

### systemd "Failed with result 'signal'" during restart

Expected and harmless. During `v2x_run_car` (which calls `systemctl restart`), the old process receives SIGTERM. If it doesn't exit within ~5 s, the system sends SIGKILL. The message appears in the log for the old process, not the new one. The new service starts and runs correctly.

### Known quirks

- **Battery voltage reads ~4.7 V** — STM32 ADC reads its internal voltage reference until an external voltage divider is wired to the ADC pin. Once the divider is in place the reading is real pack voltage.
- **Ambulance OBU uses ephemeral port** — `obu_local.json` shows `udp_listen_port: 0`. The actual port varies per restart and is chosen by the OS. This is intentional.
- **Desktop restart + OBU still visible** — correct behavior. The OBU re-authenticates every 2 s and re-registers itself automatically when Desktop comes back. To get a truly clean slate, stop both robot services before restarting Desktop.
- **STM32 USB must be unplugged** during normal operation — USB overrides UART on the STM32 board.
