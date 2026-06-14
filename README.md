# V2X Autonomous Emergency Vehicle Priority Platform

**This project demonstrates authenticated V2X emergency vehicle priority — from
cryptographic session establishment to physical lane evasion — on autonomous vehicles
operating in the real world, on real hardware, with no simulation and no human
intervention at any stage.**

---

## The Demonstration

Two autonomous ground robots drive laps around an oval track.

An emergency vehicle approaches from behind. It cryptographically authenticates itself
with a roadside unit. The roadside unit issues a signed, encrypted emergency event.
The car receives it, independently cross-checks the ambulance's position via direct
Pi-to-Pi UDP broadcast, and decides — autonomously — to yield.

The car moves to the inner edge. The ambulance passes. The car recovers and resumes speed.

The chain begins with elliptic-curve key provisioning.
It ends with wheels on a physical track.
Every step in between is real.

---

## Hardware

<!-- Add robot photo: place image at assets/robot.jpg and update the line below -->
<!-- ![Wolf Platform Robot](assets/robot.jpg) -->

The robots run on the **Wolf platform** — powder-coated aluminium chassis, high-grip
wheels, ring-lit camera mount, built for field use.

Each robot carries:

- Raspberry Pi 5
- Custom-designed and fabricated STM32F405 motor controller
- STM32 runs RTOS with hardware encoders on all four wheels — 20 Hz closed-loop velocity control
- Downward-facing camera for real-time lane detection and AprilTag localization

This is not a development kit wired together. It is a purpose-built platform.

---

## Two Systems. One Integration.

This repository contains two independently functional platforms that together form a
complete cyber-physical V2X system:

### `robot_python/` — Autonomous Robot Platform

Lane following with computer vision, AprilTag-based localization, five-state emergency
evasion state machine, STM32 motor control over the Lyra binary protocol, live MJPEG
telemetry stream, joystick override. Runs entirely on Raspberry Pi 5 — no laptop,
no ROS, no cloud dependency at runtime.

Three swappable lane-following algorithms. Pluggable motor controller. Configurable
AprilTag layout. Built with defined interfaces so any layer can be replaced without
touching the rest.

### `v2x_testbed/` — V2X Authentication Infrastructure

32-step mutual authentication protocol, AES-256-GCM encrypted post-auth messaging,
RSU session management, real-time WebSocket dashboard, SQLite audit logging,
pluggable cryptographic provider.

PlaceholderProvider (ECDSA/ECDH) is active for development. LatticeProvider interface
is ready — plug in a post-quantum implementation when it exists and the protocol does
not change.

---

## Engineering Scope

| Domain | Role in this system |
|---|---|
| Embedded Systems | STM32F405, RTOS, hardware encoders on four wheels, custom PCB |
| Computer Vision | Real-time lane detection, AprilTag localization |
| Robotics | Autonomous navigation, five-state emergency evasion |
| V2X Networking | OBU/RSU authentication, RSU-mediated UDP event broadcast |
| Applied Cryptography | ECDH, ECDSA, HKDF, AES-256-GCM, HMAC-SHA-256 |
| Distributed Systems | Multi-node coordination with no central controller |
| Real-Time Control | 20 Hz guaranteed motor loop, closed-loop velocity via encoders |
| Human-Machine Interfaces | Live WebSocket dashboard, MJPEG stream with telemetry overlay |
| Edge Computing | Full autonomy stack on-device, no external dependency at runtime |
| Autonomous Navigation | Three swappable algorithms: centroid, pure pursuit, recorded-path |

This platform contains enough material for four independent final-year projects.
This work required all of them to exist simultaneously and operate as a single system.

---

## Documentation

| Document | Purpose |
|---|---|
| [HOW_IT_ALL_WORKS.md](HOW_IT_ALL_WORKS.md) | Complete system explanation from first principles — start here |
| [WORKING_WITH_V2X.md](WORKING_WITH_V2X.md) | Operational guide: startup, joystick, dashboard, troubleshooting |
| [SETUP_PYTHON.md](SETUP_PYTHON.md) | Robot environment setup on a fresh Raspberry Pi |
| [TRACK_DESIGN.md](TRACK_DESIGN.md) | Arena layout, AprilTag placement, zone numbering |
| [v2x_testbed/README.md](v2x_testbed/README.md) | V2X authentication stack: protocol spec, build, run |

---

## Quick Start

Desktop and RSU must be running before starting the robots.

```bash
# Desktop (any machine on the network)
cd v2x_testbed/desktop
python3 server.py

# Car (Raspberry Pi)
cd robot_python
python3 main_car.py

# Ambulance (Raspberry Pi)
cd robot_python
python3 main_ambulance.py
```

Full startup sequence with verification at every step: [WORKING_WITH_V2X.md](WORKING_WITH_V2X.md)

---

## Status

| Component | State |
|---|---|
| V2X Authentication — 32-step mutual auth protocol | Operational |
| Robot Mobility — lane following, emergency evasion | Operational |
| Real-Time Dashboard | Operational |
| End-to-End Authentication Latency | 9.4ms (PlaceholderProvider, localhost) |
| Post-Quantum Crypto — LatticeProvider | Interface complete, implementation pending |

---

*Siliris Technologies Pvt. Ltd. — 2026*
