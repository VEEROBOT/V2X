# Working with V2X

Operational guide — how to start everything, what to expect, and how to fix it when things go wrong.

---

## Project Status

### Done
- Car Pi + Ambulance Pi: Ubuntu 24.04, libcamera, venv, systemd service auto-starts on boot
- Camera: IMX219 on CSI0, 320×240 via picamera2
- STM32 UART motor control over `/dev/ttyRobot` (works on RPi 4 and RPi 5, any kernel)
- Joystick: starts **disarmed** on boot → press **Start** to arm; deadman LB, turbo LB+RB
- Lane follower: white centre-line PID
- Emergency handler: NORMAL → EVADING → HOLDING → RESUMING → NORMAL
- V2X chain: OBU ↔ RSU ↔ Desktop working (auth succeeds, 3 entities shown with both robots)
- Timestamp tolerance fixed: `delta_ts_ms: 500` in RSU and OBU configs
- Unified `config.yaml` with `car:` / `ambulance:` role sections — no per-device manual edits
- `setup.sh` fully automated for both roles: venv, libcamera, udev, OBU build, service install
- RSU emergency alert: broadcasts to `192.168.0.255` — reaches all robots automatically
- `TRACK_DESIGN.md`: 16×16 ft loop, 18 AprilTags, lane markings, focal_px calibration steps

### Pending — hardware
- [ ] Build physical track (foam tiles, white/yellow tape)
- [ ] Print 18 AprilTags (IDs 0–17, 10 cm × 10 cm) — see `TRACK_DESIGN.md`
- [ ] Calibrate `focal_px` after track is built
- [ ] Tune HSV thresholds (`white_v_low`, `yellow_h_low/high`) under real lighting

### Pending — software
- [ ] End-to-end V2X test with both physical robots on track
- [ ] LatticeProvider crypto — customer implements 12 virtual methods (placeholder works for demo)

### Known quirks
- Keys must be cleared together: if RSU re-registers → OBU must also re-register or KC1/KC2 will fail
- KC2 timeout = stale session in RSU DB → clear `database/` + `rsu/build/keys/` + Pi `keys/`, restart in order
- `battery_v` in STM32 telemetry reads internal ADC reference (~4.7 V), not actual battery
- RPi 5 older kernels (≤6.8.0-1031) expose an internal RP1 UART as `/dev/ttyAMA0` with hardware loopback — fixed by using `/dev/ttyRobot` (setup.sh handles this automatically)
- STM32 USB cable must be **unplugged** from Pi during normal operation — if connected, STM32 routes all UART responses to USB and the Pi sees nothing on ttyRobot

---

## Network Layout

| Device | IP | Role |
|--------|----|------|
| Laptop | `192.168.0.103` | Runs RSU + Desktop server |
| Car Pi | `192.168.0.100` | Runs `v2x_car` service |
| Ambulance Pi | `192.168.0.104` | Runs `v2x_ambulance` service |

All three must be on the **same WiFi network**.

Adding more robots: give each Pi a unique hostname, run `setup.sh car` or `setup.sh ambulance` — they auto-register with a unique entity ID derived from hostname.

---

## What Runs Where

```
LAPTOP (192.168.0.103)
  ├── Desktop server   — python3 server.py       → Dashboard at http://localhost:5000
  └── RSU binary       — ./rsu_server ...         → UDP 5000 (authenticates OBUs)
                                                  → TCP 8001/8002 (entity registration)
                                                  → TCP 9000 (log receiver)
                                                  → UDP 5001 broadcast (emergency alerts)

CAR PI (192.168.0.100)
  └── v2x_car service  — main_car.py             → auto-starts on boot, starts DISARMED
        ├── Camera (IMX219 on CSI0)
        ├── STM32 motor controller (/dev/ttyRobot)
        ├── Joystick (/dev/input/js0) — auto-detects, retries every 5s if not found at boot
        ├── OBU client (authenticates once, exits — session lasts 5 min)
        └── RSU alert listener (UDP 5001 ← RSU broadcasts EMERGENCY_ACTIVE here)

AMBULANCE PI (192.168.0.104)
  └── v2x_ambulance service — main_ambulance.py  → auto-starts on boot
        ├── Camera, STM32, Joystick (same as car)
        └── OBU client (loops forever — keeps emergency active while service runs)
```

---

## Starting Everything

### Order is critical: Desktop → RSU → Pis

The Desktop distributes public keys during registration. RSU must register with Desktop **before** OBU does.

---

### Fresh start (first time, or after clearing sessions)

**Step 0 — Laptop: clear old keys and sessions**
```bash
cd ~/V2X/v2x_testbed
rm -f database/v2x_testbed.db database/master_secret.bin
rm -rf rsu/build/keys/
```
Also on each Pi (if keys exist from a previous run):
```bash
rm -rf ~/projects/V2X/robot_python/keys/
```

---

**Step 1 — Laptop: start Desktop server**
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
Open `http://localhost:5000` in a browser.

**Step 2 — Laptop: start RSU** (new terminal)
```bash
cd ~/V2X/v2x_testbed/rsu/build
./rsu_server ../config/rsu_config.json
```
Expected:
```
[RSU] ΔTS: 500 ms
[RSU] Car alert target: 192.168.0.255:5001   ← broadcast
```
Desktop terminal shows: `[REG] RSU registered`

**Step 3 — Car Pi: restart service**
```bash
sudo systemctl restart v2x_car
sudo journalctl -fu v2x_car
```
Expected car Pi log:
```
[OBU] [REG] ✓ Registration complete.  PK: 65 bytes  Peers: 1
[OBU] [AUTH] SESSION ESTABLISHED SUCCESSFULLY
[OBU] OBU process exited (rc=0). Emergency clears in 5s.
V2X CAR ROBOT READY
```
Then press **Start** on the joystick to arm the car.

**Step 4 — Ambulance Pi: restart service**
```bash
sudo systemctl restart v2x_ambulance
sudo journalctl -fu v2x_ambulance
```
Expected ambulance Pi log:
```
[OBU] [REG] ✓ Registration complete.  PK: 65 bytes  Peers: 2
[OBU] [AUTH] SESSION ESTABLISHED SUCCESSFULLY
V2X AMBULANCE ROBOT READY
```

---

### Normal restart (keys already exist from a previous good run)

```bash
# Laptop: start Desktop, then RSU (same order, no key clearing needed)
# Car Pi:
sudo systemctl restart v2x_car
# Ambulance Pi:
sudo systemctl restart v2x_ambulance
```

---

## What to Expect on the Dashboard

After both Pis connect:

| Field | Expected |
|-------|----------|
| ENTITIES | **3** — RSU + Car OBU + Ambulance OBU |
| SESSIONS ✓ | increments on each service restart |
| TS FAILURES | 0 |
| AVG LATENCY | ~15 ms over WiFi |
| Events | AUTH_REQUEST → TIMESTAMP_CHECK_PASS → SESSION_ESTABLISHED |

---

## Testing the Emergency Chain

### Full test with both robots

1. Start both services (Steps 3 + 4 above)
2. Ambulance OBU authenticates with `is_emergency: true` → RSU sends EMERGENCY_ACTIVE broadcast → car yields
3. Car logs: `RSU ALERT: EMERGENCY ACTIVE` → `EVADING → HOLDING`
4. `sudo systemctl stop v2x_ambulance` → emergency clears in 5 s → car logs `RESUMING → NORMAL`

### Manual simulation (no ambulance robot needed)

Run from laptop while car service is running:
```bash
python3 -c "
import socket, json, time
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.sendto(json.dumps({'type':'EMERGENCY_ACTIVE','session_id':'test-001'}).encode(), ('192.168.0.100', 5001))
print('Alert sent')
time.sleep(8)
s.sendto(json.dumps({'type':'EMERGENCY_CLEARED','session_id':'test-001'}).encode(), ('192.168.0.100', 5001))
print('Cleared')
"
```

---

## Joystick Controls

| Input | Action |
|-------|--------|
| Press **Start** (btn 7) | **Arm** — robot starts moving (autonomous or joystick) |
| Press **Start** again | **Disarm** — robot stops |
| Hold **LB** (btn 4) | Override to joystick manual control |
| Hold **LB + RB** (btn 4+5) | Turbo mode (0.8 m/s) |
| Left stick Y | Forward / reverse |
| Right stick X | Steer left / right |
| Release LB | Return to autonomous lane following |

Robot starts **disarmed** on boot. Press Start once to begin. Joystick auto-connects within 5 s of the USB dongle enumerating.

---

## Useful Commands

### Car Pi
```bash
# Service control
sudo systemctl start   v2x_car
sudo systemctl stop    v2x_car
sudo systemctl restart v2x_car
sudo journalctl -fu    v2x_car          # live logs
sudo journalctl -u     v2x_car -n 100   # last 100 lines

# Motor + telemetry test (stop service first)
sudo systemctl stop v2x_car
cd ~/projects/V2X/robot_python && source .venv/bin/activate
python3 test_driver.py    # shows live telemetry
python3 motor_test.py     # drives forward 3 s

# Manual emergency test
python3 control_socket.py --port 5010 emergency_on
python3 control_socket.py --port 5010 emergency_off
python3 control_socket.py --port 5010 arm
python3 control_socket.py --port 5010 status
```

### Ambulance Pi
```bash
# Service control
sudo systemctl start   v2x_ambulance
sudo systemctl stop    v2x_ambulance
sudo systemctl restart v2x_ambulance
sudo journalctl -fu    v2x_ambulance

# Motor + telemetry test (stop service first)
sudo systemctl stop v2x_ambulance
cd ~/projects/V2X/robot_python && source .venv/bin/activate
python3 test_driver.py
python3 motor_test.py
```

### Laptop
```bash
# Fresh start — clear old sessions before a demo
cd ~/V2X/v2x_testbed
rm -f database/v2x_testbed.db database/master_secret.bin
rm -rf rsu/build/keys/

# Check clock sync on Pi (run on Pi)
timedatectl status    # should show: System clock synchronized: yes
```

---

## Key Config Files

All configs live in the repo on the Car Pi. Edit here → commit → push → `git pull` on other devices.

| File | Controls |
|------|----------|
| `robot_python/config.yaml` | All robot settings — shared base + per-role `car:` / `ambulance:` sections |
| `v2x_testbed/obu/config/obu_local.json` | **gitignored** — generated by `setup.sh` per device (entity_id, is_emergency) |
| `v2x_testbed/obu/config/obu1_config.json` | OBU base — RSU IP, Desktop IP (both robots use this as template) |
| `v2x_testbed/rsu/config/rsu_config.json` | RSU — alert broadcast IP/port, timestamp tolerance |

### config.yaml role sections

```yaml
# Per-role settings — no manual editing needed on individual Pis
car:
  lane_follower:
    linear_speed: 0.20       # m/s
  v2x_bridge:
    obu_loop_count: 1        # authenticate once, OBU exits (session lasts 5 min)
  control:
    port: 5010

ambulance:
  lane_follower:
    linear_speed: 0.28       # m/s — faster so ambulance catches up
  v2x_bridge:
    obu_loop_count: 0        # loop forever — keeps emergency active
  control:
    port: 5011
```

```json
// rsu_config.json — key values
{
  "car_alert_ip": "192.168.0.255",   // broadcast — reaches all robots on subnet
  "car_alert_port": 5001,
  "delta_ts_ms": 500                 // 500ms tolerance (50ms was too tight for WiFi)
}
```

```json
// obu1_config.json — update if laptop IP changes
{
  "rsu_ip": "192.168.0.103",
  "desktop_ip": "192.168.0.103"
}
```

---

## Git Workflow

**Car Pi is the source of truth.** All edits happen here.

```bash
# On Car Pi — after any change:
git add <files>
git commit -m "description"
git push origin main

# On Laptop / Ambulance Pi:
git pull
```

Never edit files directly on the laptop or ambulance Pi.

---

## Adding a New Robot

1. Flash Ubuntu 24.04, set unique hostname (e.g. `v2x-car2`, `v2x-emgy2`), enable SSH
2. `git clone https://github.com/VEEROBOT/V2X.git ~/projects/V2X`
3. Edit RSU/Desktop IPs in OBU config:
   ```bash
   nano ~/projects/V2X/v2x_testbed/obu/config/obu1_config.json
   # set rsu_ip and desktop_ip → laptop IP
   ```
4. Run setup:
   ```bash
   sudo bash ~/projects/V2X/robot_python/setup.sh car    # or: ambulance
   sudo reboot
   ```

`setup.sh` generates `obu_local.json` automatically (unique entity_id from hostname, correct `is_emergency` flag). No other manual edits needed. The robot auto-registers with the RSU on first boot.

---

## Troubleshooting

### KC1 verify fail — `KC1_VERIFY_FAIL`
RSU re-registered (got new keys) but OBU still has the old RSU public key.

**Rule: if RSU keys are cleared, clear OBU keys on all Pis too.**

```bash
rm -rf ~/projects/V2X/robot_python/keys/
sudo systemctl restart v2x_car   # or v2x_ambulance
```

### KC2 timeout — `Timeout waiting for KC2`
RSU has a stale session. Full clear on laptop:
```bash
cd ~/V2X/v2x_testbed
rm -f database/v2x_testbed.db database/master_secret.bin
rm -rf rsu/build/keys/
```
Also clear OBU keys on each Pi. Then follow the full Fresh Start sequence.

### ENTITIES = 0 on Dashboard
RSU registered with Desktop before Desktop was running, or OBU registered before RSU. Always start in order: Desktop → RSU → Pis.
```bash
rm -rf ~/V2X/v2x_testbed/rsu/build/keys/
rm -rf ~/projects/V2X/robot_python/keys/
# Then: Desktop → RSU → Pi
```

### TIMESTAMP_CHECK_FAIL
`delta_ts_ms` in `rsu_config.json` is too tight or the laptop didn't `git pull`.
```bash
# Laptop:
cd ~/V2X && git pull
# Restart RSU
```

### Robot doesn't move after boot
Normal — robot starts **disarmed**. Press **Start** button (btn 7) on joystick to arm.
Or arm via socket:
```bash
cd ~/projects/V2X/robot_python && source .venv/bin/activate
python3 control_socket.py --port 5010 arm   # car
python3 control_socket.py --port 5011 arm   # ambulance
```

### Joystick not detected at boot
The USB receiver takes a few seconds to enumerate. The joystick thread retries every 5 s — wait 10 s after boot before testing. Check detection:
```bash
ls /dev/input/js0
```
If missing, unplug and replug the USB dongle.

### STM32 not responding (`test_driver.py` returns `None`)
```bash
ls -la /dev/ttyRobot         # must exist (symlink to ttyAMA10 on RPi 5)
groups                       # must include: dialout
```
If ttyRobot is missing, re-apply the udev rule:
```bash
echo 'KERNEL=="ttyAMA10", SYMLINK+="ttyRobot"' | sudo tee /etc/udev/rules.d/99-uart-v2x.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

### STM32 responds on USB but not UART (`test_driver.py` returns `None` or loopback)
The STM32 USB cable is plugged into the Pi. When USB is connected, STM32 routes all UART responses to USB.
**Fix: unplug the USB cable from the STM32 board.** Only UART TX/RX/GND wires should be connected.

### STM32 `Telemetry size mismatch: got 0, expected 70`
The Pi is receiving its own transmitted bytes back (hardware loopback). On RPi 5 with older kernel (≤1031), `/dev/ttyAMA0` is an internal RP1 UART with loopback — not the GPIO UART. Using `/dev/ttyRobot` (which points to `ttyAMA10`) fixes this.

### RSU alert not received (no EVADING in car logs)
```bash
sudo journalctl -u v2x_car | grep "RSU alert listener"
# must show: RSU alert listener started on UDP port 5001
```
Check `v2x_bridge: manual_mode: false` in `config.yaml`.
RSU broadcasts to `192.168.0.255` — car must be on the same subnet.

### Camera not working
```bash
dmesg | grep imx219    # should show: registered
# ribbon cable must be in CAM/DISP 0 (not port 1)
```

### Battery voltage shows ~4.7V in logs
Normal — STM32 reads its internal ADC reference voltage, not the actual battery. Ignore.

---

## Port Reference

| Port | Protocol | Direction | Purpose |
|------|----------|-----------|---------|
| 5000 (UDP) | UDP | OBU → RSU | V2X authentication |
| 5000 (HTTP) | HTTP | Browser → Desktop | Dashboard UI |
| 5001 | UDP | RSU → all robots | Emergency alert broadcast |
| 5002 | UDP | Car ↔ Ambulance | Position sharing (subnet broadcast) |
| 5003 | UDP | OBU listen | OBU receive port |
| 5010 | UDP | Local | Car control socket (arm/disarm/estop) |
| 5011 | UDP | Local | Ambulance control socket |
| 8001 | TCP | OBU → Desktop | OBU entity registration |
| 8002 | TCP | RSU → Desktop | RSU entity registration |
| 9000 | TCP | RSU → Desktop | Audit log stream |
