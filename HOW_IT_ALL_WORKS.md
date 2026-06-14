# How It All Works — Complete System Explanation

> This document explains the full V2X + robot system from first principles.
> Covers: what each piece does, how they connect, what happens when you start the robots,
> how the car knows the ambulance is behind it, what happens when sensors fail, and
> what Algorithm / Crypto / Lattice mean in this context.

---

## 1. The Two Projects and How They Relate

You have two things that appear separate but are tightly coupled at runtime:

```
v2x_testbed/          ← the AUTHENTICATION layer
  ├── desktop/        ← key authority + dashboard (runs on laptop)
  ├── rsu/            ← roadside authentication server (runs on laptop)
  └── obu/            ← vehicle authentication client (binary, runs on each Pi)

robot_python/         ← the ROBOT layer
  ├── main_car.py        ← car brain (camera → lane → yield logic)
  ├── main_ambulance.py  ← ambulance brain (camera → lane → emergency broadcast)
  ├── v2x_bridge.py      ← the glue between the two projects
  ├── position_broadcaster.py  ← direct Pi-to-Pi position sharing (no laptop needed)
  └── emergency_handler.py     ← the yield state machine
```

**The V2X testbed handles WHO IS ALLOWED to be in the system and WHAT EMERGENCY SIGNALS mean.**
**The robot layer handles WHERE THE ROBOT IS and HOW IT MOVES.**
**v2x_bridge.py is the single file that connects them.**

---

## 2. What Runs Where at Runtime

```
LAPTOP / DESKTOP PC
┌────────────────────────────────────────────────────────────────┐
│  [Terminal 1]  Desktop server  (Python)   port 5000 (HTTP)     │
│    - Issues cryptographic keys to everyone who registers       │
│    - Runs the dashboard you see in the browser                 │
│    - Accepts heartbeats from robots (ONLINE/OFFLINE status)    │
│                                                                │
│  [Terminal 2]  RSU binary  (C++)          port 5000 (UDP)      │
│    - Authenticates OBU packets                                 │
│    - When it sees an ambulance: broadcasts EMERGENCY_ACTIVE    │
│      → UDP broadcast to 192.168.0.255:5001 (every robot hears)│
└────────────────────────────────────────────────────────────────┘

CAR Pi  (v2x-car-01)
┌────────────────────────────────────────────────────────────────┐
│  [systemd: v2x_car]        main_car.py                         │
│    Camera → lane follower → emergency handler → motor driver   │
│    + OBU subprocess (C++ binary, authenticates with RSU)       │
│    + RSU alert listener (UDP 5001 — hears EMERGENCY_ACTIVE)    │
│    + Position broadcaster (UDP 5002 — sends zone to ambulance) │
│    + Position receiver    (UDP 5002 — receives zone from amb.) │
│    + Heartbeat sender     (HTTP POST → laptop:5000 every 15s)  │
│                                                                │
│  [systemd: v2x_obu_trigger]  v2x_obu_trigger.py               │
│    Watches joystick Mode button → starts/stops v2x_car         │
└────────────────────────────────────────────────────────────────┘

AMBULANCE Pi  (v2x-emgy)
┌────────────────────────────────────────────────────────────────┐
│  [systemd: v2x_ambulance]   main_ambulance.py                  │
│    Camera → lane follower → motor driver                       │
│    + OBU subprocess (re-authenticates every ~30s with RSU)     │
│    + Position broadcaster (UDP 5002 — sends zone to car)       │
│    + Position receiver    (UDP 5002 — receives zone from car)  │
│    + Heartbeat sender     (HTTP POST → laptop:5000 every 15s)  │
│                                                                │
│  [systemd: v2x_obu_trigger]  v2x_obu_trigger.py               │
│    Watches joystick Mode button → starts/stops v2x_ambulance   │
└────────────────────────────────────────────────────────────────┘
```

---

## 3. What Happens When You Start the Robots (Step by Step)

### Prerequisites: Desktop and RSU must be running first

The RSU needs a cryptographic keypair from the Desktop before it can authenticate anyone.
OBUs need the RSU's public key before they can authenticate.
**Order always: Desktop → RSU → Robots.**

---

### Press Start (btn 7) on the Car

The `v2x_car` service is already running since boot. The car was in **DISARMED** state — camera is on, OBU is authenticating, but **motors don't move**.

Pressing Start arms the robot:
1. `joystick.py` detects the button press
2. `main_car.py` sets `_robot_armed = True`
3. The main loop starts sending `(vx, wz)` commands to the STM32 motor driver
4. The lane follower takes over: camera sees white line → centroid controller → robot drives

---

### What the Car Does Every Tick (20 Hz)

```
Every 50ms:
  1. Grab frame from camera (picamera2, 320×240 BGR)
     Camera faces DOWN at the floor.
  2. Crop top 40% (far-field floor) — keep only the near-field directly ahead.
     Far-field has perspective distortion and stray marks; near-field centroid
     gives cleaner, more immediate steering feedback.
  3. Lane follower:
       → HSV threshold → find white line centroid
       → compute error (centroid vs frame centre)
       → proportional control → output (vx, wz)
  4. Position estimator:
       → every 3rd frame: detect AprilTags (ArUco 36h11)
       → if inner tag (0–9) seen: update zone = tag_id
       → broadcast zone to ambulance via UDP
  5. Emergency handler:
       → update_emergency(bridge.is_emergency())
       → update_own_position(own_pos)
       → update_peer_position(broadcaster.get_peer_position())
       → (vx, wz) = handler.process(vx, wz, ...)
  6. Send (vx, wz) to STM32
  7. Push frame to stream server (MJPEG)
```

---

### What the Ambulance Does Every Tick (20 Hz)

Almost identical to the car, except:
- No `EmergencyHandler` — the ambulance never yields, it drives straight through
- OBU sends `is_emergency: true` in its post-auth message → triggers RSU broadcast
- Also broadcasts its position to the car via UDP 5002

---

## 4. How the Emergency Chain Works (Full Path)

This is the core of V2X. There are **two parallel signals** that both need to be true before the car yields:

```
Signal A — V2X Authentication Chain (WHO is emergency):
  Ambulance OBU → RSU → RSU broadcasts EMERGENCY_ACTIVE → Car hears it

Signal B — Direct Position Sharing (WHERE is the ambulance):
  Ambulance → UDP broadcast 192.168.0.255:5002 → Car receives zone number
```

**Both A and B must be active for the car to yield.**
If A is true but B is unknown → car waits (logs "waiting for position fix")
If B is known but A is false → car ignores it (no authenticated emergency)

---

### Signal A: The V2X Authentication Chain in Detail

```
Step 1: Desktop issues keys to everyone during registration
  Desktop → Ambulance OBU: RID, AID, DAID, SK, PK_self, PK_RSU
  Desktop → RSU: same structure + PK_OBU (ambulance's public key)

Step 2: Ambulance OBU sends AuthRequest to RSU (UDP port 5000)
  - Generates random PID_OBU (session identifier)
  - Performs ECDH key exchange using RSU's public key
  - Signs the whole packet with its private key (ECDSA P-256)
  - Packet: [PID_OBU | timestamp | encapsulated_key | signature]

Step 3: RSU validates the AuthRequest
  - Checks timestamp is within ±500ms (prevents replay attacks)
  - Verifies signature using ambulance's public key
  - Performs ECDH decapsulation to get shared secret
  - Derives session keys via HKDF: SK_enc (encryption) + SK_mac (integrity)
  - Creates session entry in session table (expires after 60s)
  - Sends AuthResponse back to ambulance

Step 4: Both sides confirm keys (mutual authentication, KC1/KC2)
  - Ambulance sends KC1: proves it derived the same session keys
  - RSU validates KC1, sends KC2: session fully established

Step 5: Ambulance OBU sends post-auth message (AES-256-GCM encrypted)
  Payload (JSON): { "entity_id": "V2X_EMGY", "is_emergency": true, ... }
  Encrypted with SK_enc, HMAC with SK_mac

Step 6: RSU decrypts, reads is_emergency: true
  → RSU broadcasts: EMERGENCY_ACTIVE (UDP to 192.168.0.255:5001)
  → EVERY robot on the subnet hears this

Step 7: Car's RSU alert listener receives EMERGENCY_ACTIVE
  → v2x_bridge.py sets self._emergency = True
  → emergency_handler.update_emergency(True) called on next tick

Repeat: Ambulance OBU re-authenticates every ~30s (60 post-auth messages × 500ms)
        → keeps RSU session alive → RSU keeps broadcasting EMERGENCY_ACTIVE
```

---

### Signal B: Direct Position Sharing (No Laptop Involved)

```
Ambulance Pi                               Car Pi
    │                                          │
    │  every 100ms (10 Hz):                    │
    │  get own zone from position estimator    │
    │  → JSON: {role:"ambulance", zone:7,      │
    │           distance_m:0.35}               │
    │  → UDP sendto 192.168.0.255:5002 ───────►│
    │                                          │  position_broadcaster._recv_loop()
    │                                          │  receives packet, stores:
    │                                          │  peers["192.168.0.104"] = {
    │                                          │    zone: 7, role: ambulance,
    │                                          │    updated: time.monotonic()
    │                                          │  }
    │                                          │
    │                                          │  main loop calls:
    │                                          │  broadcaster.get_peer_position()
    │                                          │  → returns {zone:7, distance_m:0.35}
    │                                          │    (if data < 5s old)
    │                                          │
    │                                          │  emergency_handler.update_peer_position()
    │                                          │  sets self._amb_zone = 7
```

**This is purely Pi-to-Pi UDP. No laptop, no RSU, no internet. Just WiFi.**

---

## 5. How the Car Decides Whether to Yield

This is `emergency_handler._should_yield()`:

```python
def _should_yield(self) -> bool:
    # Gate 1: Is there an authenticated emergency?
    if not self._emergency:
        return False          # No V2X signal → never yield

    # Gate 2: Is position data available and fresh?
    if not self._position_known():
        # Logs "waiting for position fix" (rate-limited to once/5s)
        return False          # Signal but no position → WAIT, don't yield

    # Gate 3: Is the ambulance actually BEHIND the car?
    behind = self._is_amb_behind()
    gap    = self._amb_gap()
    if behind and gap <= self._yield_gap:   # yield_zone_gap = 3
        return True           # Ambulance ≤ 3 zones behind → YIELD

    return False              # Ambulance ahead or too far back → not yet
```

### What "behind" means

The oval has 10 inner tags (zones 0–9) in clockwise order.
Two separate checks run in sequence:

**Check 1 — Direction: is the ambulance in the "behind half" of the circle?**
`_is_amb_behind()` computes `diff = (own_zone - amb_zone) % 10`.
If `0 < diff ≤ 5` → ambulance is in the rear half → "behind".
If `diff > 5` → ambulance is in the front half → "ahead".
This is just direction arithmetic on a circular track — the 5-zone threshold is half of 10.

**Check 2 — Proximity: is the ambulance close enough to trigger yield?**
Only if check 1 is True AND `gap ≤ yield_zone_gap (3)`.

```
   0
9     1
8       2
7       3
   6 5 4

Car at zone 5, ambulance at zone 3:
  diff = (5-3) % 10 = 2  → behind (2 ≤ 5) AND gap 2 ≤ 3 → YIELD

Car at zone 5, ambulance at zone 1:
  diff = (5-1) % 10 = 4  → behind (4 ≤ 5) AND gap 4 > 3 → no yield yet
  (ambulance is too far back — wait for it to close in)

Car at zone 3, ambulance at zone 5:
  diff = (3-5) % 10 = 8  → NOT behind (8 > 5) → ambulance is AHEAD
  → no yield regardless of distance
```

---

## 6. How the Car Knows the Ambulance Has Passed (While in HOLDING)

This is subtle. When the car is in HOLDING it is hugging the inner island yellow line —
it cannot see any inner AprilTags. Yet it still needs to know when the ambulance has passed.

The answer is: **it uses a frozen zone and the ambulance's live UDP broadcast.**

`_position_known()` only requires `self._own_zone >= 0` — meaning the car has *ever* seen a
tag, not that it is currently seeing one. `_own_zone` is the last zone the car saw before
it started EVADING. That value is frozen but still valid as a track position reference.

Meanwhile the ambulance **never stops broadcasting its zone** at 10 Hz on UDP 5002,
even while it drives past the yielding car.

```
Before EVADING:   car's _own_zone = 5 (last seen inner tag)
                  ambulance _amb_zone = 3 (it's 2 zones behind)

Car enters EVADING → HOLDING
  car stops seeing inner tags — _own_zone stays at 5

Ambulance continues driving:
  _amb_zone = 4 → 5 → 6 → 7  (via live UDP)

Car checks _is_amb_behind() each tick:
  diff = (5 - 7) % 10 = 8   →  8 > 5  →  NOT behind  →  ambulance has passed!
  1 second grace period → RECOVERING
```

There are 3 exit paths from HOLDING, in priority order:

| Exit | How it triggers |
|------|----------------|
| Ambulance zone flips to "ahead" | Ambulance UDP zone crosses car's frozen zone + 1s grace period |
| V2X emergency clears | Ambulance OBU stops / B button pressed → `_emergency=False` + 1s grace |
| 30-second hard timeout | `elapsed >= hold_timeout_s` — always fires, no data needed |

The 30s timeout is the ultimate safety net — even if both position data and V2X
simultaneously drop while in HOLDING, the car recovers in at most 30 seconds.

---

## 7. What Happens If the Ambulance Misses a Tag?

This is the key safety question.

### Case 1: Ambulance misses one or two tags

The ambulance's position estimator keeps its **last known zone**.
Position broadcaster sends that last-known zone at 10Hz.
The car receives `zone=7` (for example) continuously even if the ambulance hasn't seen a new tag.
**Nothing changes — the last-known zone is good enough for ~1 lap.**

### Case 2: Ambulance sees NO tags for more than 5 seconds

`position_broadcaster.py` has `_PEER_STALE_S = 5.0`.
After 5 seconds without a new UDP packet from the ambulance, `get_peer_position()` returns None.
`emergency_handler._position_known()` checks if the peer data is fresh (< 3 seconds in the handler itself).
→ Returns False → `_should_yield()` returns False → **car does NOT yield.**

**This is safe:** the car just continues following the white lane. It does not swerve, does not stop, does not do anything unexpected. It simply waits for position information to return before making any yield decision.

### Case 3: V2X drops but position is still being received

If the RSU goes down or the OBU fails, `self._emergency` becomes False.
Gate 1 in `_should_yield()` fails immediately.
Car ignores all position data and just follows the lane.
**Emergency avoidance REQUIRES authenticated V2X. Position data alone is not enough.**

### Case 4: What if the ambulance is one tag behind and the car has no tag data?

The car has its own position issue — it hasn't seen an inner tag recently.
`self._own_zone = -1` → `_position_known()` checks `self._own_zone >= 0` → returns False.
Car waits. Does not yield. Does not crash.

### Summary: failure mode is always "do nothing" not "do something wrong"

```
Emergency signal? | Position known? | Result
──────────────────┼─────────────────┼──────────────────────────
      No          |      Any        | Follow lane normally
      Yes         |      No         | Follow lane, wait for fix
      Yes         |      Yes        | Check zones, possibly yield
```

---

## 8. The Yield Sequence (When Everything Works)

When `_should_yield()` returns True, the emergency handler runs a state machine:

```
NORMAL → EVADING → HOLDING → RECOVERING → RESUMING → NORMAL

NORMAL:    car follows white lane at full speed

EVADING:   car turns right toward inner island (yellow line)
           angular_speed = 0.35 rad/s rightward, linear = 0.06 m/s
           continues until it sees the inner yellow tape (boundary_near)
           or the evasion timer expires (evasion_duration_s = 6s)

HOLDING:   car creeps slowly along the inner island wall
           waits here until:
           - ambulance overtakes (amb_zone passes car's zone)
           - then waits clear_delay_s (1s grace period)
           OR V2X emergency cleared + 1s
           OR hold_timeout_s (30s) elapses

RECOVERING: car arcs left back toward white line
            at recovery_angular_speed, exits when white line re-found
            or recovery_duration_s (2.5s) elapses

RESUMING:  ramps speed from 0 back up to normal over ramp_duration_s (2s)
           smooth re-entry to full-speed lane following

NORMAL:    back to regular driving
```

---

## 9. The Algorithm Layer — What It Does

`robot_python/algorithms/` contains the lane-following brains. There are three implementations:

### `centroid.py` — Default (what runs in production)

```
Frame → crop top 40% → convert to HSV → threshold for white and yellow

WHITE detection:
  HSV range: H=0-180, S=0-70, V=190-255 (low saturation, high brightness)
  → finds the white oval lane markings on the floor
  → computes centroid X of the largest white contour
  → error = centroid_x - frame_centre_x
  → wz = -kP * error / (frame_width/2)    ← proportional steering

YELLOW detection (boundary repulsion):
  HSV range: H=20-35, S=80-255, V=80-255
  → finds the inner island yellow tape
  → if yellow centroid is too close (> yellow_repel_frac of frame width)
    → override steering away from yellow

LOST mode:
  → No white detected for > 4s: slow down to 50% speed, keep turning
  → No white for > 8s: stop completely

Output: (vx m/s, wz rad/s) → goes into emergency_handler.process() → motor driver
```

### `pure_pursuit.py` and `recorded_path.py`

Alternative algorithms: one uses geometric path planning, the other replays a recorded set of motor commands. Not used in normal V2X operation — the centroid follower is active.

---

## 10. The Crypto Layer — What It Does and Why

The cryptographic protocol exists to answer **one question with certainty:**

> "Is this vehicle that claims to be an ambulance actually our registered ambulance, right now, and not someone spoofing it?"

Without authentication, any device could broadcast "I am an emergency vehicle" on UDP 5001 and all cars would yield — a trivial attack.

### The 32-Step Protocol (simplified)

```
Before anything happens: REGISTRATION (one-time)
  Desktop generates EC P-256 keypair for each entity
  Desktop sends to ambulance OBU:
    - RID   (random ID — what you call yourself on the wire)
    - AID   (authentication ID — your cryptographic identity)
    - DAID  (derived AID — for key derivation)
    - SK    (your private key — never leaves your device)
    - PK_self (your public key)
    - PK_RSU  (RSU's public key — to encrypt to the RSU)
  Desktop sends to RSU:
    - same structure + PK_OBU (ambulance's public key)

During operation: AUTHENTICATION (every ~30 seconds)
  Ambulance OBU → RSU:
    AuthRequest = PID_OBU | timestamp | ECDH_encapsulate(PK_RSU) | ECDSA_sign(SK)

  RSU:
    1. Check: timestamp within ±500ms?    → reject if old (replay prevention)
    2. Check: ECDSA signature valid?       → reject if wrong (forgery prevention)
    3. ECDH decapsulate → shared secret
    4. HKDF(shared_secret, context) → SK_enc + SK_mac
    5. Send AuthResponse + KC2

  After session established: OBU sends post-auth AES-GCM message
    Plaintext: {"entity_id": "V2X_EMGY", "is_emergency": true}
    Encrypted: AES-256-GCM with SK_enc (nonce + ciphertext + 16B auth tag)
    Protected:  HMAC-SHA-256 with SK_mac over the ciphertext

  RSU decrypts → reads is_emergency → broadcasts EMERGENCY_ACTIVE
```

### Why each step exists

| Step | What it prevents |
|------|-----------------|
| Timestamp check ±500ms | Replay attack — attacker records a valid packet and replays it later |
| ECDSA signature | Forgery — attacker crafts a fake AuthRequest |
| ECDH encapsulation | Man-in-the-middle — attacker intercepts and reads/modifies traffic |
| AES-256-GCM | Eavesdropping on post-auth data |
| HMAC on ciphertext | Bit-flipping attack on encrypted payload |
| KC1/KC2 exchange | Ensures both sides derived the SAME session keys (mutual auth) |

---

## 11. The Lattice Layer — What It Is

"Lattice" refers to **lattice-based cryptography**, a family of mathematical problems that are believed to resist attacks by quantum computers.

### The problem with classical crypto (what we use now)

ECDH and ECDSA are based on the **elliptic curve discrete logarithm problem** — hard for regular computers but breakable by a large enough quantum computer using Shor's algorithm.

### What lattice crypto uses instead

Problems based on **Learning With Errors (LWE)** — finding a hidden linear structure in a noisy system. No known quantum algorithm speeds this up significantly.

Specific algorithms for this system (planned, not yet active):
- **CRYSTALS-Dilithium** — replaces ECDSA signatures
- **CRYSTALS-Kyber** — replaces ECDH key encapsulation

### How it's structured in the code

```
v2x_testbed/protocol/crypto/
  crypto_provider.h       ← abstract interface (pure virtual class)
    virtual encapsulate()
    virtual decapsulate()
    virtual sign()
    virtual verify()
    virtual derive_keys()

  placeholder_provider.cpp  ← ACTIVE: classical ECDH+ECDSA (OpenSSL)
  lattice_provider.cpp      ← STUBBED: interface implemented, algorithm not yet wired
```

The entire authentication protocol (all 32 steps) calls only the abstract interface.
To switch from classical to post-quantum: change one line in `rsu_config.json`:
```json
"crypto_provider": "lattice"    // was: "placeholder"
```

### What this means for the robots

**The robots don't know or care** which crypto provider is active. The RSU still broadcasts `EMERGENCY_ACTIVE` on UDP 5001 either way. The position sharing still uses plain UDP either way. Crypto only affects whether the authentication step is quantum-resistant.

---

## 12. Can It Work Without the Laptop? Partially.

| Component | Needs Laptop? | What breaks without it |
|-----------|--------------|----------------------|
| Lane following | No | Nothing — robots drive independently |
| Position sharing | No | Direct Pi-to-Pi UDP |
| Emergency yield (car) | **YES** | Car never gets EMERGENCY_ACTIVE signal |
| Dashboard | Yes | No visibility |
| Key provisioning | Yes (once) | OBU can't authenticate on first run |

**If you run `v2x_run_car` with the laptop available once, the OBU gets its keys.**
After that, the OBU binary uses those cached keys and can re-authenticate. However, if keys are cleared or expire, the laptop is needed again.

The **short answer**: robots can follow lanes without the laptop. They can share position without the laptop. But the car will **never yield** without the RSU broadcasting the emergency signal.

---

## 13. What Happens When You Put Two Robots on the Track and Start Them

Here is the exact sequence assuming everything is already running:

```
t=0s    Car and ambulance armed (Start button pressed on each)
        Both start following the white line at ~0.20 m/s

t=0–2s  OBU authentication in progress
        Car OBU → RSU: AuthRequest
        RSU → Car OBU: AuthResponse + KC2 → session established
        (Car post-auth: is_emergency=false → no broadcast)

        Ambulance OBU → RSU: AuthRequest  
        RSU → Ambulance OBU: AuthResponse + KC2
        Ambulance post-auth: is_emergency=true
        → RSU broadcasts EMERGENCY_ACTIVE to 192.168.0.255:5001

t=2s    Car's RSU alert listener receives EMERGENCY_ACTIVE
        v2x_bridge._emergency = True
        emergency_handler.update_emergency(True)

t=2s–?  Position data being exchanged at 10Hz via UDP 5002
        Car knows: "ambulance is at zone X"
        Car checks: is ambulance ≤ 3 zones behind me?

        If ambulance is AHEAD of car:   no yield, car drives normally
        If ambulance is FAR behind:     no yield, waiting for it to catch up
        If ambulance is 1–3 zones behind and catching up: YIELD triggered

t=?     Car enters EVADING → HOLDING → RECOVERING → RESUMING
        Ambulance drives straight past on the main oval
        Car resumes normal lane following

t=~32s  Ambulance OBU re-authenticates (session about to expire)
        RSU broadcasts EMERGENCY_ACTIVE again
        Cycle continues indefinitely
```

---

## 14. The Road Ahead — Closing the Loop on Evasion

The one genuine architectural criticism worth acting on is this: **evasion recovery is still
partially time-based.** "Turn left for 2.5 seconds" depends on floor friction, battery charge,
and motor wear. Every track change requires retuning. Here is how to fix it — no new hardware
needed.

### What we already have (and most people don't realise)

The STM32 telemetry already sends `gyro_z` (yaw rate) and `wheel_ticks[4]` every 100ms.
The emergency handler already accepts `white_found` and exits RECOVERING early when the
white line is detected. The yellow-line proportional controller (`_yellow_steer`) is already
closed-loop during EVADING. The hard part is done.

### The four improvements, in order of impact

**1. Geometry-based RECOVERING instead of time-based**
During RECOVERING, integrate `gyro_z` from STM32 telemetry to measure how many degrees the
robot has actually turned. Target: ~30°. Stop the arc when rotation is achieved, not when
a timer fires. Repeatability stops depending on environment entirely.

**2. Dead-reckoning between AprilTag sightings**
Use `wheel_ticks` to estimate distance traveled since the last tag. If zone 5 was seen
0.4 m ago at known tag spacing, position is approximately zone 5 + 65% of the way to zone 6.
Localization becomes continuous, not snapshot-based.

**3. Variable crop ratio by state**
```
NORMAL    → 40% crop (current — near-field centroid, clean signal)
EVADING   → 20% crop (see yellow line approaching sooner, more warning)
RECOVERING→  0% crop (maximum frame to catch the white line as early as possible)
HOLDING   → irrelevant (not tracking lines, just creeping)
```
One parameter change per state. Zero new hardware.

**4. Exit RECOVERING on centroid, not time**
The white line centroid is already computed during RECOVERING. Exit the arc the moment
the centroid crosses the frame centre (steering error crosses zero) rather than waiting
for `recovery_duration_s` to elapse. This is one condition added to the existing early-exit
check — the code already handles it for `white_found`, just not for centroid position.

These four changes together turn the evasion sequence from
*"command, wait, hope"* into *"command, measure, confirm"* —
which is what every professional system does.

---

## 15. Why This Work Matters

At first glance, the demonstration is straightforward.

Two vehicles on a track. An ambulance approaches from behind. A car yields.
The ambulance passes. The car resumes normal operation.

The entire sequence takes under a minute.

What that minute required is the subject of this section.

---

### The Chain

The chain begins with mathematics.

An emergency vehicle cryptographically proves its identity to a roadside unit:
elliptic-curve key provisioning, ECDH session establishment, ECDSA digital signatures,
HKDF session key derivation, AES-256-GCM encrypted messaging, HMAC-SHA-256 integrity
validation. Thirty-two steps. Every one of them happens in under 10 milliseconds.

The roadside unit validates the session and issues an authenticated emergency event
over UDP to every node on the subnet.

At the same time — entirely independent of the V2X stack — each robot reads AprilTag
markers with a downward-facing camera and broadcasts its zone directly to the subnet
at 10 Hz. The car knows where the ambulance is. The V2X system and the position system
never talk to each other. The car's state machine combines them.

Three conditions must all be true before the car does anything:

1. Is the emergency event V2X-authenticated?
2. Is the ambulance's position known and fresh?
3. Is the ambulance close enough and behind the car?

Only when all three are true does the evasion sequence begin.

The car moves to the inner edge. It holds while the ambulance passes. It recovers and
resumes speed.

**No human presses a button at any stage. No script injects a trigger. No simulation
stands in for any component.**

The chain begins with cryptographic key provisioning.
It ends with wheels turning on a physical track.
Every link in between is real.

---

Most V2X research demonstrations look like this:

```
Node A sends a UDP packet that says "I am an emergency vehicle"
Node B receives it and prints a message
```

That is not V2X. That is a hello world program with a siren sticker on it.

---

### Scale

This work spans engineering domains that are normally taught as separate courses and
staffed by separate teams:

| Domain | What it means in this system |
|--------|------------------------------|
| Embedded Systems | STM32F405, RTOS, hardware encoders, custom-designed and fabricated PCB |
| Computer Vision | Real-time lane detection and AprilTag localization under real lighting |
| Robotics | Five-state emergency evasion state machine, closed-loop velocity control |
| V2X Networking | OBU/RSU architecture, 32-step mutual authentication, live UDP broadcast |
| Applied Cryptography | ECDH, ECDSA, HKDF, AES-256-GCM, HMAC-SHA-256 |
| Distributed Systems | Multi-node coordination with no central controller, peer failure tolerance |
| Real-Time Control | 20 Hz motor loop at guaranteed timing via RTOS |
| Human-Machine Interfaces | WebSocket dashboard, MJPEG video with live telemetry overlay |
| Edge Computing | Full stack on Raspberry Pi 5 — no cloud, no laptop required at runtime |
| Autonomous Navigation | Three swappable lane-following algorithms, tunable per deployment |

Each of these domains is a substantial engineering discipline on its own.

This platform contains enough material for four independent final-year projects.

One team could spend a semester on the robot alone.
A second on the V2X authentication stack.
A third on the dashboard and monitoring infrastructure.
A fourth on the cryptographic protocol.

This work required all four to exist simultaneously and operate as a single system.

---

### A Platform, Not a Proof of Concept

Most demonstrations are built for one outcome. This one was designed with defined
interfaces at every boundary so that any layer can be replaced without touching the rest.

**Lane-following algorithm:** centroid, pure pursuit, or recorded-path — one line in
`config.yaml`. The robot does not know which one is running.

**Cryptographic provider:** placeholder (ECDSA/ECDH) or lattice (post-quantum) —
the 32-step protocol does not change. The interface is already there. Plug in the
post-quantum implementation when it is ready.

**AprilTag layout:** change the number of inner or outer track markers in config —
the localization logic and yield decision adapt automatically.

**Motor controller:** Lyra binary protocol over UART — the STM32 firmware can be
retargeted without touching a single line of Python.

Swappable algorithms. Swappable crypto. Swappable hardware targets.

This was not built for a single demonstration. It was built to be extended.

---

### The Hardware

The robots run on the Wolf platform: powder-coated aluminium chassis, high-grip wheels,
ring-lit camera mount, purpose-built for field use.

The STM32 motor controller is a custom-designed and fabricated PCB. It runs a real-time
operating system. It reads four hardware encoders — one per wheel. The motor control loop
executes at a guaranteed 20 Hz regardless of what the Raspberry Pi is doing at that moment.

Hardware encoders mean the robot follows a commanded velocity — it does not guess.
RTOS means the control loop is never preempted by a lower-priority task.
These are not implementation details. They are the difference between a robot that
behaves predictably and one that does not.

The camera observes real lane markings under real and variable lighting.
The wireless network carries real latency and real packet loss.
Authentication occurs on a live network, not a loopback interface.

Nothing is controlled. Nothing is ideal. Nothing is simulated.

---

### The Moment It Becomes Undeniable

The cryptography is invisible. The ECDH, the HKDF, the AES-GCM — none of it is visible
to someone standing at the side of the table.

What is visible is this:

Two robots are driving laps around an oval track.
A browser dashboard shows both — green dots, entity IDs, live session counts, 9ms latency.
The ambulance reaches the car from behind.
The car moves to the inner edge of the track.
The ambulance passes.
The car recovers and resumes speed.
The dashboard shows: EMERGENCY_PRIORITY_GRANTED. No failures.

Nobody in that room is thinking about the mathematics.

They are thinking: *this works.*

That is the point.

---

### In One Sentence

**This project demonstrates authenticated V2X emergency vehicle priority — from
cryptographic session establishment to physical lane evasion — on autonomous vehicles
operating in the real world, on real hardware, with no simulation and no human
intervention at any stage.**

---

## 16. One-Line Summary of Each File

| File | What it does |
|------|-------------|
| `main_car.py` | The car's brain — reads camera, follows lane, asks handler if it should yield |
| `main_ambulance.py` | The ambulance's brain — reads camera, follows lane, broadcasts emergency |
| `emergency_handler.py` | State machine: NORMAL/EVADING/HOLDING/RECOVERING/RESUMING |
| `v2x_bridge.py` | Runs OBU subprocess, listens for RSU alerts, exposes `is_emergency()` |
| `position_broadcaster.py` | UDP 10Hz position sharing between robots, no laptop needed |
| `position.py` | AprilTag detector — tells you which zone the robot is in |
| `algorithms/centroid.py` | Lane follower — finds white line, computes steering |
| `stream_server.py` | MJPEG HTTP server — serves camera view to browser |
| `robot_driver.py` | STM32 UART driver — translates (vx, wz) into wheel commands |
| `v2x_obu_trigger.py` | Watches joystick Mode button, starts/stops the robot service |
| `desktop/dashboard/app.py` | Flask server, WebSocket push of auth events, entity status |
| `desktop/registration/reg_server.py` | Issues cryptographic keys to OBUs and RSU |
| `rsu/src/packet_processor.cpp` | Validates AuthRequests, runs ECDH, creates sessions |
| `rsu/src/session_manager.h` | Tracks active sessions, expires them after 60s |
