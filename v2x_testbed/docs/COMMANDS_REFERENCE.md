# V2X Testbed Commands Reference Guide

**Quick Navigation:** All commands organized by task. Find what you need in seconds.

---

## 📋 Table of Contents

1. [Kill All Instances](#kill-all-instances)
2. [Clean State (DB, Keys, Artifacts)](#clean-state)
3. [Build System](#build-system)
4. [Run Interactive System](#run-interactive-system)
5. [Run Tests](#run-tests)
6. [Run Performance Tests](#run-performance-tests)
7. [Dashboard Access](#dashboard-access)
8. [View Logs](#view-logs)
9. [Git Operations](#git-operations)
10. [Quick Cheat Sheet](#quick-cheat-sheet)

---

## 🛑 Kill All Instances

**Scenario:** You need to stop all running services (Desktop, RSU, OBU).

### Kill Everything

```bash
pkill -f server.py          # Kill Desktop Python server
pkill -f rsu_server         # Kill RSU C++ server
pkill -f obu_client         # Kill OBU C++ client
```

### Kill Specific Service

```bash
# Kill only Desktop
pkill -f server.py

# Kill only RSU
pkill -f rsu_server

# Kill only OBU
pkill -f obu_client
```

**Location:** These commands are hardcoded in all three scripts (`scripts/run_*.sh`)

---

## 🧹 Clean State

**Scenario:** Start fresh - remove old database, keys, and build artifacts.

### Full Clean (Everything)

```bash
# Clean database
rm -f desktop/database/v2x_testbed.db
rm -f desktop/database/master_secret.bin

# Clean keys (all OBU/RSU instances)
rm -rf obu/build/keys
rm -rf obu/build/keys_obu2
rm -rf rsu/build/keys
```

### Clean Only Database

```bash
rm -f desktop/database/v2x_testbed.db desktop/database/master_secret.bin
```

### Clean Only Keys

```bash
rm -rf obu/build/keys obu/build/keys_obu2 rsu/build/keys
```

### Clean Build Artifacts

```bash
rm -rf obu/build
rm -rf rsu/build
rm -rf protocol/build
```

**Recommendation:** Always run these cleanups before starting fresh tests.

**Location:** These commands are in all three scripts (`scripts/run_*.sh`)

---

## 🔨 Build System

### Build Everything (One Command)

```bash
# From project root
cd /home/dev/v2x_testbed

# Build Protocol Library
cd protocol
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)

# Build RSU
cd ../../rsu
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)

# Build OBU
cd ../../obu
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
```

### Build Individual Components

```bash
# Protocol only
cd protocol/build && make -j$(nproc)

# RSU only
cd rsu/build && make -j$(nproc)

# OBU only
cd obu/build && make -j$(nproc)
```

### Verify Builds

```bash
# Check if all executables exist
[ -x protocol/build/test_crypto ] && echo "✓ test_crypto" || echo "✗ test_crypto"
[ -x protocol/build/test_packets ] && echo "✓ test_packets" || echo "✗ test_packets"
[ -x protocol/build/test_protocol_flow ] && echo "✓ test_protocol_flow" || echo "✗ test_protocol_flow"
[ -x rsu/build/rsu_server ] && echo "✓ rsu_server" || echo "✗ rsu_server"
[ -x obu/build/obu_client ] && echo "✓ obu_client" || echo "✗ obu_client"
```

**File Location:** [README.md](../README.md#build--run) (lines 119-157)

---

## 🚀 Run Interactive System

**Scenario:** Run Desktop, RSU, OBU live in separate terminals for manual testing.

### Option 1: Use Automated Script (Recommended)

```bash
cd /home/dev/v2x_testbed
./scripts/run_system_live.sh
```

**What It Does:**
- Kills all old processes
- Cleans database and keys
- Builds RSU and OBU
- Starts Desktop, RSU, OBU in parallel
- Keeps all processes running (doesn't auto-cleanup)
- Opens dashboard at http://localhost:5000
- Waits for Ctrl+C to stop

**File Location:** [scripts/run_system_live.sh](../scripts/run_system_live.sh)

### Option 2: Manual Multi-Terminal Run

**Terminal 1 – Clean & Start Desktop:**

```bash
cd /home/dev/v2x_testbed/desktop
rm -f database/v2x_testbed.db database/master_secret.bin
python3 server.py
```

**Terminal 2 – Start RSU:**

```bash
cd /home/dev/v2x_testbed/rsu/build
./rsu_server ../config/rsu_config.json
```

**Terminal 3 – Start OBU (Single Instance):**

```bash
cd /home/dev/v2x_testbed/obu/build
./obu_client ../config/obu1_config.json
```

**Terminal 4 – Start OBU2 (Optional - Second Instance):**

```bash
cd /home/dev/v2x_testbed/obu/build
./obu_client ../config/obu2_config.json
```

**Terminal 5 – View Logs (Optional):**

```bash
tail -f /home/dev/v2x_testbed/logs/*.log
```

**File Location:** [README.md](../README.md#️-run-the-system) (lines 126-155)

---

## 🧪 Run Tests

### Protocol Tests (Unit + Integration)

```bash
cd /home/dev/v2x_testbed/protocol/build

./test_crypto                    # Crypto provider tests
./test_packets                   # Packet serialization tests
./test_protocol_flow             # Full 32-step auth tests
```

### All Tests Together

```bash
cd /home/dev/v2x_testbed/protocol/build
./test_crypto && ./test_packets && ./test_protocol_flow && echo "✓ All tests passed"
```

**Output:** PASS/FAIL messages for each test case

**File Location:** [README.md](../README.md#️-build-protocol-library) (lines 119-127)

---

## ⚡ Run Performance Tests

**Scenario:** Measure authentication latency, throughput, packet loss across multiple loops.

### Basic Performance Test (10 Loops)

```bash
cd /home/dev/v2x_testbed
./scripts/run_performance_test.sh
```

### Custom Loop Count

```bash
./scripts/run_performance_test.sh 100           # 100 authentication cycles
./scripts/run_performance_test.sh 200           # 200 authentication cycles
./scripts/run_performance_test.sh 50            # 50 authentication cycles
```

### With Crypto Provider Specification

```bash
./scripts/run_performance_test.sh 100 PlaceholderProvider   # ECDSA-based
./scripts/run_performance_test.sh 100 LatticeProvider       # Post-quantum (when available)
```

### What It Produces

**Console Output:**
- Test progress (building, starting services, running loops)
- Per-loop statistics (latency, throughput)
- Summary report

**Files Generated:**
```
results/
├── performance_report_20260224_193451.md        # Full metrics report
└── sysinfo_20260224_193451.txt                  # System info snapshot
```

### View Latest Performance Report

```bash
cat results/performance_report_*.md | tail -100
```

**File Location:** [scripts/run_performance_test.sh](../scripts/run_performance_test.sh) (lines 1-80 for header)

**Full Documentation:** [docs/PERFORMANCE_TESTING.md](./PERFORMANCE_TESTING.md)

---

## 📊 Dashboard Access

**Scenario:** View real-time authentication events, sessions, and metrics.

### Open Dashboard

```
http://localhost:5000
```

### What You See

- **Overview Tab:** Registered OBUs, RSU config, live event feed
- **Performance Tab:** Throughput, packet loss, latency graphs
- **Events Tab:** Raw authentication event log
- **Export Tab:** Download session data as CSV/JSON

### Check Dashboard Logs (Python)

```bash
tail -f logs/desktop_live.log
```

**Requirement:** Desktop server must be running (started by `run_system_live.sh` or manually)

**File Location:** [desktop/dashboard/app.py](../desktop/dashboard/app.py)

---

## 📝 View Logs

### All Logs

```bash
ls -la /home/dev/v2x_testbed/logs/
```

### Real-Time Tail All Logs

```bash
tail -f /home/dev/v2x_testbed/logs/*.log
```

### Specific Logs

```bash
tail -f /home/dev/v2x_testbed/logs/desktop_live.log     # Desktop server
tail -f /home/dev/v2x_testbed/logs/rsu_live.log         # RSU server
tail -f /home/dev/v2x_testbed/logs/obu_live.log         # OBU client
```

### View Database Audit Log

```bash
sqlite3 /home/dev/v2x_testbed/desktop/database/v2x_testbed.db ".mode column" "SELECT * FROM events LIMIT 20;"
```

**File Location:** [logs/](../logs/) directory

---

## 🔗 Git Operations

**For detailed git reference, see:** [docs/GIT_COMMANDS.md](./GIT_COMMANDS.md)

### Check Status

```bash
git status                           # Current state
git log --oneline -10                # Last 10 commits
git log --oneline --graph --all      # Visual history
```

### Commit Changes

```bash
git add .                            # Stage all files
git commit -m "Description of changes"
git push origin main                 # Push to GitHub
```

### View Changes Before Committing

```bash
git diff                  # All unstaged changes
git diff --staged         # Staged changes only
git diff README.md        # Specific file changes
git show <commit-hash>    # Specific commit
```

### Discard Local Changes (Use With Care)

```bash
# Discard one file
git restore README.md

# Discard ALL local changes
git restore .

# Reset to last commit (discard everything)
git reset --hard HEAD
```

### Pull Latest from GitHub

```bash
git fetch origin
git pull origin main
```

**File Location:** [docs/GIT_COMMANDS.md](./GIT_COMMANDS.md)

---

## 📱 Quick Cheat Sheet

| **Task** | **Command** |
|----------|-----------|
| Kill all services | `pkill -f server.py; pkill -f rsu_server; pkill -f obu_client` |
| Clean everything | `rm -f desktop/database/*.db desktop/database/*.bin; rm -rf obu/build/keys* rsu/build/keys` |
| Build all | `cd protocol/build && make -j$(nproc); cd ../../rsu/build && make -j$(nproc); cd ../../obu/build && make -j$(nproc)` |
| Run live system | `./scripts/run_system_live.sh` |
| Run tests | `protocol/build/test_crypto && protocol/build/test_packets && protocol/build/test_protocol_flow` |
| Run perf (10 loops) | `./scripts/run_performance_test.sh 10` |
| Run perf (100 loops) | `./scripts/run_performance_test.sh 100` |
| Open dashboard | `http://localhost:5000` |
| View logs | `tail -f logs/*.log` |
| Check git status | `git status` |
| Commit & push | `git add .; git commit -m "description"; git push` |

---

## 🗂️ What's Where?

| **Category** | **File** | **Purpose** |
|--------------|----------|-----------|
| **Interactive System** | [scripts/run_system_live.sh](../scripts/run_system_live.sh) | Run Desktop + RSU + OBU with automatic cleanup & dashboard |
| **Full System Test** | [scripts/run_full_system_test.sh](../scripts/run_full_system_test.sh) | Automated security test suite (not commonly used) |
| **Performance Tests** | [scripts/run_performance_test.sh](../scripts/run_performance_test.sh) | Multi-loop performance measurement with loop count support |
| **Manual Build/Run** | [README.md](../README.md) | Step-by-step build and run instructions |
| **Performance Testing Guide** | [docs/PERFORMANCE_TESTING.md](./PERFORMANCE_TESTING.md) | Detailed performance testing methodology and interpretation |
| **Git Reference** | [docs/GIT_COMMANDS.md](./GIT_COMMANDS.md) | All git operations and workflows |
| **This File** | [docs/COMMANDS_REFERENCE.md](./COMMANDS_REFERENCE.md) | **← YOU ARE HERE** - All commands in one place |

---

## 🎯 Common Workflows

### "I want to start fresh and test the system"

```bash
# 1. Kill everything
pkill -f server.py; pkill -f rsu_server; pkill -f obu_client

# 2. Clean state
rm -f desktop/database/v2x_testbed.db desktop/database/master_secret.bin
rm -rf obu/build/keys* rsu/build/keys

# 3. Run the system
./scripts/run_system_live.sh

# 4. Open dashboard in browser
# http://localhost:5000
```

### "I need to measure performance (100 loops)"

```bash
./scripts/run_performance_test.sh 100
```

### "I want to run unit tests"

```bash
protocol/build/test_crypto && protocol/build/test_packets && protocol/build/test_protocol_flow
```

### "I modified code and need to rebuild"

```bash
cd obu/build && make -j$(nproc)       # If you modified OBU
cd ../../../rsu/build && make -j$(nproc)  # If you modified RSU
cd ../../../protocol/build && make -j$(nproc) # If you modified Protocol
```

### "I want to commit my changes"

```bash
git status                # See what changed
git diff README.md        # Preview changes
git add .                 # Stage everything
git commit -m "Brief description of changes"
git push origin main      # Push to GitHub
```

---

## ❓ FAQ

**Q: Where does the database get stored?**
A: `desktop/database/v2x_testbed.db` — Deleted when you run `rm -f desktop/database/v2x_testbed.db`

**Q: Where are authentication keys stored?**
A: `obu/build/keys/` and `rsu/build/keys/` — Deleted when you run `rm -rf obu/build/keys* rsu/build/keys`

**Q: How do I run two OBUs simultaneously?**
A: In separate terminals, run both:
```bash
./obu/build/obu_client obu/config/obu1_config.json
./obu/build/obu_client obu/config/obu2_config.json
```

**Q: How do I see real-time logs while system is running?**
A: `tail -f /home/dev/v2x_testbed/logs/*.log`

**Q: Can I run performance tests with custom loop count?**
A: Yes: `./scripts/run_performance_test.sh 200` (for 200 loops)

**Q: Where are performance reports saved?**
A: `results/performance_report_*.md` — Timestamped automatically

**Q: What's the difference between the three scripts?**
A: 
- `run_system_live.sh` → **USE THIS** for manual testing (keeps services running)
- `run_full_system_test.sh` → Advanced security test suite (rarely needed)
- `run_performance_test.sh` → **USE THIS** for benchmarking (supports `--loop N`)

---

**Last Updated:** February 24, 2026  
**Version:** 1.0  
**Author:** Praveen Kumar  
**Company:** Siliris Technologies Pvt. Ltd
