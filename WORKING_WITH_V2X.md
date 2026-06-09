# Working with V2X

Operational guide — how to start everything, what to expect, and how to fix it when things go wrong.

---

## Network Layout

| Device | IP | Role |
|--------|----|------|
| Laptop | `192.168.0.103` | Runs RSU + Desktop server |
| Car Pi | `192.168.0.100` | Runs `v2x_car` service |
| Ambulance Pi | TBD (set during setup) | Runs `v2x_ambulance` service |

All three must be on the **same WiFi network**.

---

## What Runs Where

```
LAPTOP (192.168.0.103)
  ├── Desktop server   — python3 server.py       → Dashboard at http://localhost:5000
  └── RSU binary       — ./rsu_server ...         → UDP 5000 (authenticates OBUs)
                                                  → TCP 8001/8002 (entity registration)
                                                  → TCP 9000 (log receiver)

CAR PI (192.168.0.100)
  └── v2x_car service  — main_car.py             → auto-starts on boot
        ├── Camera (IMX219 on CSI0)
        ├── STM32 motor controller (/dev/ttyAMA0)
        ├── Joystick (/dev/input/js0)
        ├── OBU client (authenticates with RSU, exits after 1 cycle)
        └── RSU alert listener (UDP 5001 ← RSU sends EMERGENCY_ACTIVE here)

AMBULANCE PI
  └── v2x_ambulance service — main_ambulance.py  → auto-starts on boot
        └── OBU client (is_emergency: true, loops forever while service runs)
```

---

## Starting Everything

### Order is critical: Desktop → RSU → Pi

The Desktop distributes public keys during registration. RSU must register with Desktop **before** OBU does — the OBU gets the RSU's public key from Desktop at registration time. Wrong order = `No peer public keys received` error and auth fails.

---

### Fresh start (first time, or after clearing sessions)

**Step 0 — Laptop: clear old keys and sessions**
```bash
cd ~/V2X/v2x_testbed
rm -f database/v2x_testbed.db database/master_secret.bin
rm -rf rsu/build/keys/
```
Also on Car Pi (if keys exist from a previous run):
```bash
rm -rf ~/projects/V2X/robot_python/keys/
```

---

**Step 1 — Laptop: start Desktop server**
```bash
cd ~/V2X/v2x_testbed/desktop
pip3 install -r requirements.txt   # first time only
python3 server.py
```
You should see:
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
RSU registers with Desktop (since keys were cleared). You should see on the Desktop terminal:
```
[REG] RSU registered
```
And RSU terminal:
```
[RSU] ΔTS: 500 ms
[RSU] Car alert target: 192.168.0.100:5001
```

**Step 3 — Car Pi: restart service**
```bash
sudo systemctl restart v2x_car
sudo journalctl -fu v2x_car        # watch live logs
```

OBU registers with Desktop (since keys were cleared), gets RSU's public key, then authenticates. Expected car Pi log:
```
[OBU] [REG] Connecting to Desktop 192.168.0.103:8001...
[OBU] [REG] ✓ Registration complete.  PK: 65 bytes  Peers: 1
[OBU] [AUTH] Step 21: Timestamp OK
[OBU] [AUTH] SESSION ESTABLISHED SUCCESSFULLY
[OBU] OBU process exited (rc=0). Emergency clears in 5s.
```

After OBU exits — that's **normal**. `obu_loop_count: 1` means the car authenticates once, the session stays active on the RSU for 5 minutes, and the OBU process exits cleanly.

---

### Normal restart (keys already exist from a previous good run)

If both RSU and OBU have their `./keys/` folders, they skip registration and go straight to auth. This is fine as long as the Desktop database still has their records (i.e. Desktop was not cleared).

```bash
# Laptop: start Desktop, then RSU (same order, no key clearing needed)
# Pi: sudo systemctl restart v2x_car
```

---

## What to Expect on the Dashboard

After car Pi starts:

| Field | Expected |
|-------|----------|
| ENTITIES | **2** — RSU + OBU1 (car) |
| SESSIONS ✓ | increments by 1 each service restart |
| TS FAILURES | 0 (fixed — delta_ts_ms: 500 in both RSU and OBU configs) |
| AVG LATENCY | ~15 ms over WiFi |
| Events | AUTH_REQUEST → TIMESTAMP_CHECK_PASS → ... → SESSION_ESTABLISHED → POST_AUTH_RECEIVED |

When ambulance is also running:

| Field | Expected |
|-------|----------|
| ENTITIES | **3** — RSU + OBU1 (car) + OBU2 (ambulance) |
| Live Events | POST_AUTH_RECEIVED with emergency flag from OBU2 |

---

## Testing the Emergency Chain

### Without ambulance robot (laptop simulation)

Run this on the laptop while car service is running:
```bash
python3 -c "
import socket, json, time
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.sendto(json.dumps({'type':'EMERGENCY_ACTIVE','session_id':'test-001'}).encode(), ('192.168.0.100', 5001))
print('Alert sent — watch car Pi logs')
time.sleep(8)
s.sendto(json.dumps({'type':'EMERGENCY_CLEARED','session_id':'test-001'}).encode(), ('192.168.0.100', 5001))
print('Cleared')
"
```

Car Pi should log:
```
RSU ALERT: EMERGENCY ACTIVE
EVADING  → HOLDING  → RESUMING  → NORMAL
```

### With ambulance robot

1. `sudo systemctl start v2x_ambulance` on ambulance Pi
2. OBU2 (is_emergency: true) authenticates → RSU sends EMERGENCY_ACTIVE to car → car yields
3. `sudo systemctl stop v2x_ambulance` → OBU stops → 5s later emergency clears → car resumes

---

## Joystick Controls

| Input | Action |
|-------|--------|
| Hold **LB** (btn 4) | Enable joystick — robot goes manual, autonomous pauses |
| Hold **LB + RB** (btn 4+5) | Turbo mode (0.8 m/s) |
| Press **Start** (btn 7) | Arm / Disarm toggle |
| Left stick Y | Forward / reverse |
| Right stick X | Steer left / right |
| Release LB | Return to autonomous |

Robot starts **armed**. Press Start to disarm (stops motors, won't move until re-armed).

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

# Manual emergency test (no OBU needed)
cd ~/projects/V2X/robot_python && source .venv/bin/activate
python3 control_socket.py --port 5010 emergency_on
python3 control_socket.py --port 5010 emergency_off
python3 control_socket.py --port 5010 status

# Camera test
cd ~/projects/V2X/robot_python && source .venv/bin/activate
python3 -c "
import picamera2, time
cam = picamera2.Picamera2()
cam.configure(cam.create_preview_configuration(main={'size':(320,240),'format':'BGR888'}))
cam.start(); time.sleep(2)
cam.capture_file('/tmp/test.jpg')
cam.stop(); print('Saved /tmp/test.jpg')
"

# Joystick mapping check
jstest /dev/input/js0
```

### Laptop
```bash
# Fresh start — clear old sessions before a demo
cd ~/V2X/v2x_testbed
rm -f database/v2x_testbed.db database/master_secret.bin
# then restart Desktop and RSU

# Check Pi clock sync (run on Pi)
timedatectl status    # should show: System clock synchronized: yes
```

---

## Key Config Files

All configs live in the repo on the Car Pi. Edit here → push → `git pull` on laptop.

| File | Controls |
|------|----------|
| `robot_python/config.yaml` | Everything robot-side (speeds, camera, OBU loop count, ports) |
| `v2x_testbed/obu/config/obu1_config.json` | Car OBU — RSU IP, Desktop IP, ports |
| `v2x_testbed/obu/config/obu2_config.json` | Ambulance OBU — same but `is_emergency: true` |
| `v2x_testbed/rsu/config/rsu_config.json` | RSU — car alert IP/port, timestamp tolerance |

### Critical values to know

```yaml
# config.yaml
v2x_bridge:
  obu_loop_count: 1    # car: authenticate once, OBU exits (session lasts 5 min)
                       # ambulance: change to 0 (loop forever = emergency stays active)
  manual_mode: false   # MUST be false for real V2X; true = no OBU, manual UDP only
```

```json
// rsu_config.json
{
  "car_alert_ip": "192.168.0.100",   // Car Pi's WiFi IP — UPDATE if Pi IP changes
  "car_alert_port": 5001,
  "delta_ts_ms": 500                 // 500ms timestamp tolerance (50ms was too tight for WiFi)
}
```

```json
// obu1_config.json (car) / obu2_config.json (ambulance)
{
  "rsu_ip": "192.168.0.103",         // Laptop WiFi IP — UPDATE if laptop IP changes
  "desktop_ip": "192.168.0.103"      // same laptop
}
```

---

## Git Workflow

**Car Pi is the source of truth.** All changes happen here.

```bash
# On Car Pi — after any change:
git add <files>
git commit -m "description"
git push origin main

# On Laptop:
git pull

# On Ambulance Pi (when set up):
git pull
```

Never edit files on the laptop or ambulance directly.

---

## Ambulance Setup (first time)

1. Flash Ubuntu 24.04, hostname `ambulance-robot`, SSH enabled
2. `git clone https://github.com/VEEROBOT/V2X.git ~/projects/V2X`
3. Edit OBU2 config — set RSU and Desktop IPs:
   ```bash
   nano ~/projects/V2X/v2x_testbed/obu/config/obu2_config.json
   # rsu_ip and desktop_ip → 192.168.0.103
   ```
4. Edit `config.yaml` — set ambulance to loop forever:
   ```bash
   nano ~/projects/V2X/robot_python/config.yaml
   # v2x_bridge: obu_loop_count: 0
   ```
5. Run setup:
   ```bash
   sudo bash ~/projects/V2X/robot_python/setup.sh ambulance
   sudo reboot
   ```

---

## Troubleshooting

### KC1 verify fail — `KC1_VERIFY_FAIL`
RSU and OBU have mismatched keys — RSU re-registered (got new keys) but OBU still has the old RSU public key. The shared secrets don't match so KC1 fails.

**Rule: if RSU keys are cleared, OBU keys must be cleared too.** They must always be in sync.

Fix on the Pi:
```bash
rm -rf ~/projects/V2X/robot_python/keys/
sudo systemctl restart v2x_car
```
OBU re-registers with Desktop and gets the RSU's current public key.

### KC2 timeout — `Timeout waiting for KC2`
RSU has a stale session from a previous run. On the laptop:
```bash
cd ~/V2X/v2x_testbed
rm -f database/v2x_testbed.db database/master_secret.bin
rm -rf rsu/build/keys/
```
Also clear OBU keys on Pi (`rm -rf ~/projects/V2X/robot_python/keys/`), then follow the full Fresh Start sequence above.

### ENTITIES = 0 on Dashboard (or "No peer public keys" OBU error)
The OBU registered but got no RSU public key — RSU didn't register with Desktop first. Fix:
```bash
# Laptop: stop RSU, then:
rm -rf ~/V2X/v2x_testbed/rsu/build/keys/
# Also on Pi if needed:
rm -rf ~/projects/V2X/robot_python/keys/

# Then follow the full Fresh Start sequence above:
# Desktop → RSU → Pi (in that order)
```
Desktop must be running before RSU starts, and RSU must register before OBU does.

### OBU keeps sending messages / won't stop
Closing the terminal does NOT stop the service. The service runs in the background.
```bash
sudo systemctl stop v2x_car
```

### TIMESTAMP_CHECK_FAIL in RSU logs
Fixed — `delta_ts_ms` was raised from 50 → 500 in `rsu_config.json`. If this appears again, verify the laptop did `git pull` and RSU was restarted.

### Camera not working
```bash
dmesg | grep imx219          # should show: registered
# ribbon cable must be in CAM/DISP 0 (not port 1)
```

### STM32 not connecting — serial errors
```bash
ls -la /dev/ttyAMA0          # must exist
groups                       # must include: dialout
sudo usermod -aG dialout veerobot && newgrp dialout   # if missing
```

### RSU alert not received on car (no EVADING in logs)
```bash
sudo journalctl -u v2x_car | grep "RSU alert listener"
# must show: RSU alert listener started on UDP port 5001
```
If not: check `v2x_bridge: manual_mode: false` in `config.yaml`.
Also verify RSU config `car_alert_ip` is `192.168.0.100` (not `car-robot.local`).

### Robot doesn't move / stays stopped
Press **Start** button (btn 7) to arm. Or:
```bash
cd ~/projects/V2X/robot_python && source .venv/bin/activate
python3 control_socket.py --port 5010 arm
```

### Battery voltage shows ~4.7V in logs
This is **normal** — it reads the STM32's internal ADC reference voltage, not the actual battery. Ignore this value.

---

## Port Reference

| Port | Protocol | Direction | Purpose |
|------|----------|-----------|---------|
| 5000 (UDP) | UDP | OBU → RSU | V2X authentication |
| 5000 (HTTP) | HTTP | Browser → Desktop | Dashboard UI |
| 5001 | UDP | RSU → Car Pi | Emergency alerts |
| 5002 | UDP | Car ↔ Ambulance | Position sharing |
| 5003 | UDP | OBU1 listen | Car OBU receive port |
| 5010 | UDP | Local | Car control socket (arm/disarm/estop) |
| 5011 | UDP | Local | Ambulance control socket |
| 8001 | TCP | OBU → Desktop | OBU entity registration |
| 8002 | TCP | RSU → Desktop | RSU entity registration |
| 9000 | TCP | RSU → Desktop | Audit log stream |
