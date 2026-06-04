# V2X ROS_Code — Issue Tracker

> **Last updated:** 2026-05-27

---

## Status summary

| Priority | Issue | Status |
|----------|-------|--------|
| P0 | Missing `resource/` marker files (build-breaking) | **FIXED** |
| P1 | SETUP_GUIDE binary names wrong (`rsu` / `obu`) | **FIXED** |
| P1 | SETUP_GUIDE Part 5 used `./rsu` instead of `./rsu_server` | **FIXED** |
| P2 | OBU CLI used `--config` flag; OBU expects positional arg | **FIXED** |
| P2 | `manual_mode` hardcoded `True` even when binary provided | **FIXED** |
| P3 | Bridge keywords (`EMERGENCY_ACTIVE`) didn't match OBU stdout | **FIXED** |
| P3 | OBU is one-shot; bridge expected long-running subprocess | **FIXED** |
| P3 | No "emergency cleared" signal from OBU stdout | **MITIGATED** |
| P3 | Lane follower used largest-blob only — broken centre line & thin yellow edges unreliable | **FIXED** |
| P3 | No lane offset — robot followed road centre, not left lane | **FIXED** |
| P3 | No position awareness — car yielded regardless of ambulance location | **FIXED** |
| P3 | No "ambulance passed" detection — car held position until RSU timeout | **FIXED** |
| P4 | RSU does not notify car OBU of emergency vehicle | **FIXED** |

---

## Fixed issues

### P1 — Wrong RSU binary run command in SETUP_GUIDE Part 5

**Symptom:** `./rsu: No such file or directory`

**Root cause:** SETUP_GUIDE Part 5 "Start Order" used `./rsu` as the run command.
CMake builds the binary as `rsu_server`.

**Fix applied:** Updated SETUP_GUIDE Part 5 Step 2 to `./rsu_server ../config/rsu_config.json`.

---

### P3 — Lane follower used largest-blob only; no lane offset

**Symptom 1:** On a road with thin yellow edge bars and broken white dashes,
the `max(contours, key=cv2.contourArea)` pick could latch onto a yellow edge
blob instead of the white centre dashes, causing erratic steering.

**Symptom 2:** Robot followed the geometric centre of all detected markings, not
the left lane — it drove down the middle of the road regardless of lane convention.

**Fix applied — centroid calculation:**  
`_find_centroid` now computes a **weighted centroid of ALL blobs** above `min_contour_area`
instead of picking only the largest. This averages across white dashes + yellow edges,
placing the centroid naturally within the detected lane area.

**Fix applied — lane offset:**  
Added `lane_offset_px` parameter. PID target = `frame_centre + lane_offset_px`.
- Car launch: `lane_offset_px = +60` → white centre line sits to the RIGHT → robot in LEFT lane
- Ambulance launch: `lane_offset_px = -60` → white centre line sits to the LEFT → robot in RIGHT lane

Also lowered `min_contour_area` from 300 to 150 px² to detect short dashes and thin yellow bars.

Debug image updated: orange line shows the lane target (was always just the green centre line before).

---

### P0 — Missing `resource/` marker files

**Symptom:** `colcon build` fails with ament resource index error.

**Root cause:** All four Python packages referenced `resource/<pkg_name>` in `setup.py`
but the actual empty marker files did not exist on disk.

**Fix applied:** Created empty files:
- `src/lyra_bridge/resource/lyra_bridge`
- `src/lyra_cmd_vel_gate/resource/lyra_cmd_vel_gate`
- `src/lyra_localization/resource/lyra_localization`
- `src/v2x_robot/resource/v2x_robot` (was already present)

---

### P1 — Wrong binary names in SETUP_GUIDE

**Symptom:** User runs `./rsu` or `obu/build/obu` and gets "file not found".

**Root cause:** CMake builds produce `rsu_server` and `obu_client`, not `rsu` / `obu`.
SETUP_GUIDE used the wrong names.

**Fix applied:** Updated `SETUP_GUIDE.md`:
- `./rsu` → `./rsu_server`
- `obu/build/obu` → `obu/build/obu_client`

---

### P2 — OBU CLI argument format

**Symptom:** Bridge spawns `./obu_client --config obu1_config.json` which OBU ignores,
so it always uses its default config path instead of the one passed from ROS2.

**Root cause:** OBU `main.cpp` parses config as a **positional** argument:
```
./obu_client [config_path] [--loop N]
```
The bridge was incorrectly using `['--config', path]`.

**Fix applied:** `v2x_bridge_node.py` now builds command as:
```python
cmd = [self._obu_binary]
if self._obu_config:
    cmd.append(self._obu_config)   # positional
cmd += ['--loop', '999999']
```

---

### P2 — `manual_mode` hardcoded `True` in launch files

**Symptom:** Even if user passes `obu_binary:=...` to the launch, the bridge always
ran in manual mode because the launch files set `'manual_mode': True` directly.

**Fix applied:** Removed the hardcoded override from the node logic.
`v2x_bridge_node.py` now auto-detects:
```python
if self._obu_binary and os.path.isfile(self._obu_binary):
    self._manual_mode = False   # auto-enable OBU mode
```
The `manual_mode` parameter in the launch files is now only the fallback default.

---

### P3 — Bridge keywords didn't match OBU output

**Symptom:** Bridge watches for `EMERGENCY_ACTIVE` / `EMERGENCY_CLEARED` strings
that do not appear anywhere in OBU stdout. Emergency state was never set from OBU output.

**Root cause:** Keywords were invented; actual OBU output (from `main.cpp` line 233):
```
[OBU] 🚑 Emergency priority flag sent
```

**Fix applied:** Updated `v2x_bridge_node.py` to match actual OBU stdout:
```python
_OBU_EMERGENCY_SENT = "Emergency priority flag sent"   # substring match, emoji-safe
_OBU_AUTH_FAILED    = "[OBU] FAILED:"
```

---

### P3 — OBU is one-shot; bridge expected long-running subprocess

**Symptom:** OBU runs one auth cycle and exits. Bridge's `for line in proc.stdout`
loop ends immediately. Emergency state gets stuck and OBU doesn't re-authenticate.

**Fix applied:** Bridge now passes `--loop 999999` to `obu_client` so it continuously
re-authenticates. On process exit (if it ever does exit), bridge waits
`exit_clear_delay_s` (default 5 s) then clears emergency state.

---

### P3 (Mitigated) — No "emergency cleared" signal from OBU stdout

**Situation:** OBU has no "emergency cleared" log line. Emergency is an active-vehicle
concept — the ambulance OBU keeps authenticating as long as it runs.

**Mitigation:** Emergency clears when:
1. OBU process exits → bridge clears after `exit_clear_delay_s`
2. Manual service call: `ros2 service call /v2x/set_emergency std_srvs/srv/SetBool "{data: false}"`

**Remaining gap:** In the real system, the RSU should notify the car OBU that the
ambulance has left range. This is Step 3 (see below).

---

---

### P3 — No position awareness; car yielded regardless of ambulance location

**Symptom 1:** Car yielded even when the ambulance was on the opposite side of the track (or already ahead).

**Symptom 2:** After yielding, car stayed stationary until the RSU session expired (minutes), not until the ambulance actually passed.

**Fix applied — `position_node.py` (NEW):**  
Detects AprilTag 36h11 markers embedded in the white centre-line gaps using `cv2.aruco.detectMarkers`. Publishes `/robot/position` as `{"zone": N, "distance_m": F}` at 5 Hz. Zone persists between tags. Compatible with OpenCV 4.5.x (Ubuntu 22.04).

**Fix applied — `position_broadcaster_node.py` (NEW):**  
Peer-to-peer UDP exchange on port 5002. Each robot broadcasts its own position JSON to the peer's IP. Receives peer's broadcasts and re-publishes as `/v2x/peer_position`. The transport is independent of the RSU V2X auth channel.

**Fix applied — `emergency_handler_node.py` (MODIFIED):**  
Position-aware state machine:
- **NORMAL→EVADING**: requires both `emergency_detected` AND `ambulance_behind` AND `gap ≤ yield_zone_gap (4 zones = 2 m)`
- **HOLDING→RESUMING**: triggered when ambulance zone overtakes car zone (it passed) + 1 s grace
- **Fallback**: if position unknown (no AprilTag seen yet), falls back to original V2X-only behaviour

**Fix applied — launch files (MODIFIED):**  
Both launches add `position_node`, `position_broadcaster_node`. Peer IP passed as `ambulance_ip:=...` (car) or `car_ip:=...` (ambulance) argument. Empty peer_ip = position sharing disabled gracefully.

---

## Fixed in Step 3

### P4 — RSU does not notify car of emergency vehicle

**Situation:** RSU detects ambulance emergency auth and logs the event,
but previously sent no notification to the car.

**Full implementation (RSU → UDP → Car bridge):**

Five files were modified to close this loop:

1. **`rsu/config/rsu_config.json`** — Added `car_alert_ip` and `car_alert_port` (5001)
2. **`rsu/src/session_manager.h`** — Added `has_active_emergency()` method
3. **`rsu/src/packet_processor.h`** — Added `send_car_alert(bool active, ...)` public method
4. **`rsu/src/packet_processor.cpp`** — Implemented UDP JSON send; called after emergency auth
5. **`rsu/src/main.cpp`** — Main loop tracks emergency state; sends CLEAR on session expiry

RSU sends JSON to car on UDP port 5001:
```json
{"type": "EMERGENCY_ACTIVE",  "session_id": "..."}
{"type": "EMERGENCY_CLEARED"}
```

6. **`ROS_Code/.../v2x_bridge_node.py`** — Car role starts a UDP listener thread in OBU mode.
   Receives RSU alerts and updates `_emergency` state → published on `/v2x/emergency_detected`.

**Full automatic flow:**
```
Ambulance OBU → RSU UDP auth → RSU packet_processor
  → RSU sends UDP alert to car_alert_ip:5001
    → Car v2x_bridge_node RSU listener
      → /v2x/emergency_detected = true
        → emergency_handler_node → evasion
```

---

---

### P3 — ROS2 dependency removed; pure Python stack implemented

**Request:** "ROS2 not required. Just the bridge provides output to control the robot
and gets info from the robot… one main.py with camera, another for V2X etc.. it should
still be modular, but does not need ROS2."

**Implementation (`d:/V2X/robot_python/`):**

All ROS2 nodes replaced with standalone Python modules. The Lyra binary protocol
and serial transport (`lib/protocol.py`, `lib/transport.py`, `lib/telemetry.py`)
were already pure Python and are reused verbatim.

| Old ROS2 Node | New Pure Python Module |
|---------------|----------------------|
| `lyra_bridge` node | `robot_driver.py` |
| `line_follower_node` | `lane_follower.py` |
| `position_node` | `position.py` |
| `position_broadcaster_node` | `position_broadcaster.py` |
| `v2x_bridge_node` | `v2x_bridge.py` |
| `emergency_handler_node` | `emergency_handler.py` |
| `lyra_cmd_vel_gate` (priority mux) | handled in `main_car.py` loop |
| ROS2 service calls | `control_socket.py` (UDP JSON, port 5010/5011) |
| `car.launch.py` | `main_car.py` |
| `ambulance.launch.py` | `main_ambulance.py` |

**Key design decisions:**
- Single background thread in `robot_driver.py` handles 20 Hz motor, 10 Hz telemetry, 1 Hz heartbeat
- Main camera loop drives lane following + AprilTag detection at ~30 fps
- No inter-module message bus needed — direct method calls in the main loop
- `control_socket.py` replaces `ros2 service call` for manual emergency testing

**Dependencies:** `pyserial`, `opencv-contrib-python-headless`, `numpy`, `pyyaml` — see `requirements.txt`.

---

## Minor notes (not blocking)

- `app_main.c` in STM32 code has a misleading comment "Default to USB" while
  the code sets `TRANSPORT_UART3`. Comment only — behaviour is correct.
- V2X testbed requires Linux + cmake + g++ + libssl-dev to build.
  Cannot be compiled on Windows without WSL.
- The pure Python stack does not include joystick support (not needed for the demo).
  Add `pygame` or `evdev` if joystick override is required.
