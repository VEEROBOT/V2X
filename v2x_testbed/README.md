# V2X Authentication Testbed

A research-grade Vehicle-to-Everything (V2X) authentication platform demonstrating secure communication between On-Board Units (OBU), Roadside Units (RSU), and a central Desktop authority. Implements a complete 32-step authentication protocol with pluggable cryptography, achieving **9.4ms end-to-end latency (PlaceholderProvider, localhost test)**.

---

## Overview

This testbed implements a complete authentication protocol for V2X communications:

* **Desktop Server (Python)**
  Central authority (key provisioning), audit logging, dashboard visualization

* **RSU Server (C++)**
  Roadside authentication server, session management, packet processing

* **OBU Client (C++)**
  Vehicle-side authentication agent, session establishment, key confirmation

* **Protocol Library (C++)**
  Cryptographic abstraction layer, packet serialization, authentication state machine

The system is designed as a modular research platform aligned with the V2X Authentication LLD (v1.0).

---

## Architecture

```
┌─────────────────────────────────────────┐
│         Desktop Server (Python)         │
│  ├─ Registration Server (TCP 8001/8002)│
│  ├─ Log Receiver (TCP 9000)            │
│  └─ Dashboard (HTTP 5000, WebSocket)   │
└─────────────────────────────────────────┘
         ↓ TCP (Reg)       ↑ TCP (Logs)
         ↓                 ↑
    ┌────────────┐    ┌─────────────┐
    │   OBU      │    │    RSU      │
    │ C++ Client │←→UDP:5000→│ C++ Server │
    └────────────┘    └─────────────┘
     (Vehicle)        (Roadside)
```

---

## Features

✅ **Pluggable Cryptographic Architecture (Placeholder + Lattice Interface)**
✅ **Full 32-Step Mutual Authentication Protocol**
✅ **Session Key Derivation + Key Confirmation (KC1 / KC2)**
✅ **Post-Auth AES-256-GCM Encrypted Messaging**
✅ **Emergency Vehicle Priority Detection & Signaling**
✅ **Adversarial Security Testing (Corrupt Sig, Old Timestamp, Replay)**
✅ **Real-Time Dashboard with 4 Tabs (Overview, Performance, Events, Export)**
✅ **Session Management & Cleanup**
✅ **Audit Logging to SQLite Database**
✅ **Throughput & Packet Loss Measurement**
✅ **Configuration-Driven Deployment**
✅ **Comprehensive Unit & Integration Tests**

---

## Cryptographic Model

The system supports interchangeable crypto providers via a `CryptoProvider` interface:

* **PlaceholderProvider (Active for Development)**

  * ECDSA P-256 signatures
  * ECDH-based key encapsulation
  * SHA-256 / HMAC-SHA-256
  * HKDF-based session derivation

* **LatticeProvider (Interface + Size Definitions Implemented)**

  * Designed for post-quantum algorithms (e.g., CRYSTALS-Dilithium + KEM)
  * Stubbed implementation pending production crypto integration

⚠ Current 9.4ms latency measurement uses `PlaceholderProvider` on localhost.

---

## Security Scope & Assumptions

This is a **research authentication testbed**, not a hardened production PKI system.

Assumptions:

* Secure internal network environment
* No TLS wrapping around registration channel (for research simplicity)
* File-based key storage
* No TPM / hardware secure enclave
* NTP-synchronized clocks required for timestamp validation

Designed for protocol validation, benchmarking, and demonstration — not immediate field deployment.

---

## Quick Start

### Prerequisites

```bash
sudo apt install -y build-essential cmake g++ libssl-dev python3-pip
pip3 install flask flask-socketio flask-cors cryptography --break-system-packages
```

---

## Build & Run

### 1️⃣ Build Protocol Library

```bash
cd protocol
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)

./test_crypto
./test_packets
./test_protocol_flow
```

---

### 2️⃣ Build OBU Client

```bash
cd ../../obu
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
```

---

### 3️⃣ Build RSU Server

```bash
cd ../../rsu
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
```

---

### 4️⃣ Run the System

**Terminal 1 – Desktop Server**

```bash
cd desktop
rm -f database/v2x_testbed.db database/master_secret.bin
python3 server.py
```

**Terminal 2 – RSU**

```bash
cd rsu/build
./rsu_server ../config/rsu_config.json
```

**Terminal 3 – OBU**

```bash
cd obu/build
./obu_client ../config/obu1_config.json
```

---

### Dashboard

Access:

```
http://localhost:5000
```

Provides:

* Live authentication events
* Registered entities
* Active sessions
* Real-time protocol state visibility

---

## Authentication Flow

The system executes a full 32-step protocol:

| Steps | Operation                                                               | Latency           | Notes               |
| ----- | ----------------------------------------------------------------------- | ----------------- | ------------------- |
| 1-6   | Desktop key provisioning                                                | Registration time | One-time            |
| 7-19  | OBU: PID generation, encapsulation, signing, AuthRequest                | ~3.3ms            | 282B                |
| 20-26 | RSU: Timestamp check, signature verify, decapsulation, session creation | ~4.4ms            | 249B response       |
| 27-30 | OBU: Verify RSU, derive keys, send KC1                                  | ~0.4ms            | Mutual auth         |
| 31-32 | RSU: Validate KC1, send KC2                                             | ~0.1ms            | Session established |

**Measured End-to-End Latency: 9.4ms (localhost, PlaceholderProvider)**
Target requirement: <200ms ✓

---

## Project Structure

```
v2x_testbed/
├── desktop/
│   ├── server.py
│   ├── config.py
│   ├── dashboard/
│   ├── registration/
│   ├── log_service/
│   ├── database/
│   └── tests/
│
├── obu/
│   ├── src/
│   ├── config/
│   ├── keys/              # Generated at runtime
│   ├── build/             # Build artifacts (not version controlled)
│   └── CMakeLists.txt
│
├── rsu/
│   ├── src/
│   ├── config/
│   ├── keys/              # Generated at runtime
│   ├── build/
│   └── CMakeLists.txt
│
├── protocol/
│   ├── crypto/
│   ├── packets/
│   ├── common/
│   ├── tests/
│   └── CMakeLists.txt
│
├── v2x_lld.pdf
└── README.md
```

---

## Configuration

All components are JSON-driven.

Example RSU:

```json
{
  "entity_id": "RSU001",
  "desktop_ip": "127.0.0.1",
  "desktop_port": 8002,
  "listen_port": 5000,
  "log_port": 9000,
  "crypto_provider": "PlaceholderProvider"
}
```

Switch provider:

```json
"crypto_provider": "LatticeProvider"
```

---

## Testing

### Desktop Registration Tests

```bash
cd desktop
python3 tests/test_registration.py OBU1 8001
python3 tests/test_registration.py RSU 8002
```

### Protocol Tests

```bash
cd protocol/build
./test_crypto
./test_packets
./test_protocol_flow
```

---

## Security Testing (Adversarial)

The OBU client supports test modes that intentionally send malformed packets to verify RSU rejection:

### Corrupt Signature Test

```bash
./obu_client ../config/obu1_config.json --test-mode=corrupt_signature
```

Expected: RSU rejects with `SIGNATURE_CHECK_FAIL`. Dashboard shows Sig Failures: 1.

### Old Timestamp Test

```bash
./obu_client ../config/obu1_config.json --test-mode=old_timestamp
```

Expected: RSU rejects with `TIMESTAMP_CHECK_FAIL` (60s old, exceeds 50ms threshold). Dashboard shows TS Failures: 1.

### Replay Attack Test

```bash
./obu_client ../config/obu1_config.json --test-mode=replay
```

Expected: First packet accepted, replayed packet rejected with `REPLAY_DETECTED`. Dashboard shows Replays: 1.

### Automated Security Test Suite

```bash
./scripts/run_full_system_test.sh
```

Runs all four tests (normal + 3 adversarial), reports pass/fail for each.

---

## Emergency Vehicle Priority

OBU2 is configured as an emergency vehicle. After session establishment, it sends an encrypted post-auth message with `is_emergency: true`.

```bash
# Start Desktop and RSU first, then:
cd obu/build
./obu_client ../config/obu2_config.json
```

Expected output:
- OBU: `🚑 Emergency priority flag sent`
- RSU: `🚑 EMERGENCY VEHICLE DETECTED — Granting priority`
- Dashboard: `EMERGENCY_PRIORITY_GRANTED` event, OBU2 shown with 🚑 icon

---

## Post-Authentication Messaging

After session establishment, OBU sends an AES-256-GCM encrypted message to RSU:

- **Encryption:** AES-256-GCM with `sk_enc` (12B nonce + ciphertext + 16B GCM tag)
- **Integrity:** HMAC-SHA-256 with `sk_mac` over the encrypted payload
- **Payload:** JSON with entity ID, emergency flag, session ID, status message
- **Wire format:** `[header:6B] [enc_len:4B] [encrypted] [hmac:32B]`

---

## Performance Testing

### Single Authentication Cycle (Baseline)

Run a single OBU authentication to RSU:

**Terminal 1:**
```bash
cd ~/v2x_testbed/desktop
rm -f database/v2x_testbed.db database/master_secret.bin
python3 server.py
```

**Terminal 2:**
```bash
cd ~/v2x_testbed/rsu/build
./rsu_server ../config/rsu_config.json
```

**Terminal 3:**
```bash
cd ~/v2x_testbed/obu/build
./obu_client ../config/obu1_config.json
```

Opens dashboard at `http://localhost:5000` and shows event log.

### Multi-Loop Performance Testing (10 Cycles)

Run 10 consecutive authentication cycles to measure consistency:

**Terminal 1:**
```bash
cd ~/v2x_testbed/desktop
rm -f database/v2x_testbed.db database/master_secret.bin
python3 server.py
```

**Terminal 2:**
```bash
cd ~/v2x_testbed/rsu/build
./rsu_server ../config/rsu_config.json
```

**Terminal 3 — Run 10 authentications:**
```bash
cd ~/v2x_testbed/obu/build
./obu_client ../config/obu1_config.json --loop 10
```

**Output:** Console shows latency for each cycle; dashboard displays all 10 authentication events.

### Performance Analysis

Expected results (per cycle):
- **AuthRequest Processing:** ~3.3ms
- **AuthResponse Processing:** ~4.4ms  
- **Key Confirmation:** ~0.5ms
- **Total End-to-End:** ~9.4ms

Across 10 cycles:
- ✅ Verify latency consistency (low jitter)
- ✅ Check database I/O overhead
- ✅ Monitor CPU usage on both processes
- ✅ Validate session cleanup between runs

### Automated Performance Test Script

For convenience, use the provided test script:

```bash
./scripts/run_performance_test.sh
```

This script:
1. Cleans up old databases and keys
2. Starts Desktop, RSU, OBU in background
3. Runs 10 authentication cycles
4. Collects timing statistics
5. Generates performance report
6. Cleans up processes

See `docs/PERFORMANCE_TESTING.md` for detailed analysis methodology.

---

## Performance Metrics

| Metric                    | Value     |
| ------------------------- | --------- |
| Registration Time         | <100ms    |
| AuthRequest Generation    | ~3.3ms    |
| AuthResponse Processing   | ~4.4ms    |
| Key Confirmation          | ~0.5ms    |
| **Total Auth Latency**    | **9.4ms** |
| WebSocket Dashboard Delay | <100ms    |

---

## Database

SQLite database stores:

* `entities` – Registered OBUs and RSU
* `sessions` – Authentication sessions
* `events` – Audit logs
* `crypto_timings` – Measured operation durations
* `metrics` – Latency and throughput results

---

## Development Guidance

Recommended workflow:

* Run RSU + OBU on localhost first
* Validate full 32-step flow
* Then deploy to separate hardware (Pi / NUC)
* Ensure clock synchronization (chrony/NTP)

---

## Implementation Status

| Component                  | Status                                     |
| -------------------------- | ------------------------------------------ |
| Desktop Server             | ✅ Complete                                 |
| OBU Client                 | ✅ Complete                                 |
| RSU Server                 | ✅ Complete                                 |
| Protocol Library           | ✅ Complete                                 |
| Post-Auth AES-GCM Messaging| ✅ Complete                                 |
| Emergency Vehicle Priority | ✅ Complete                                 |
| Adversarial Testing        | ✅ Complete                                 |
| Dashboard (4-tab)          | ✅ Complete                                 |
| Throughput Measurement     | ✅ Complete                                 |
| Packet Loss Tracking       | ✅ Complete                                 |
| Lattice Crypto Integration | ⚠ Interface Ready (Implementation Pending) |
| Robot Mobility (Phase 2)   | ⬜ Not Started                              |

---

## LLD Reference

See `v2x_lld.pdf` for:

* Detailed 32-step protocol definition
* State machines
* Packet formats
* Session derivation logic
* Performance instrumentation model

---

## Status

**Phase 1 Complete – Authentication Research Testbed Operational**

* End-to-end authentication verified
* Mutual authentication working
* Session key derivation validated
* Dashboard operational
* Performance metrics collected

---
