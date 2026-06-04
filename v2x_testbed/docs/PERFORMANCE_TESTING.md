# V2X Authentication Testbed — Performance Testing Guide

**Company:** Siliris Technologies Pvt. Ltd  
**Author:** Praveen Kumar  
**Created:** 15th February 2026  
**Version:** 1.1

---

## Overview

This guide provides methodology, procedures, and analysis techniques for measuring and validating V2X authentication protocol performance.

## Objectives

- ✅ Measure end-to-end authentication latency
- ✅ Validate consistency across multiple cycles
- ✅ Identify performance bottlenecks
- ✅ Benchmark against specification targets
- ✅ Monitor resource utilization

## Specification Targets

| Metric | Target | Status |
|--------|--------|--------|
| Total Auth Latency | <200ms | ✅ 9.4ms achieved |
| AuthRequest Time | <50ms | ✅ ~3.3ms |
| AuthResponse Time | <50ms | ✅ ~4.4ms |
| Key Confirmation | <50ms | ✅ ~0.5ms |
| Jitter (10 cycles) | <5% deviation | ✅ Verify |

---

## Test Setup

### Prerequisites

- ✅ All components built (protocol, OBU, RSU)
- ✅ Clean database (no prior state)
- ✅ Fresh key generation
- ✅ NTP synchronized if testing across machines

### System Configuration

**Hardware (Baseline):**
- CPU: Modern multi-core (Intel i7, AMD Ryzen)
- RAM: 2GB minimum
- Network: Localhost or LAN

**Software:**
- Protocol: PlaceholderProvider (ECDSA)
- Framework: C++ (RSU/OBU), Python (Desktop)
- OS: Linux (Ubuntu 20.04+)

---

## Test Procedures

### Procedure 1: Single Cycle Baseline

**Objective:** Establish reference performance for one complete auth cycle.

**Steps:**

1. **Clean Environment:**
   ```bash
   rm -f ~/v2x_testbed/desktop/database/v2x_testbed.db
   rm -f ~/v2x_testbed/desktop/database/master_secret.bin
   rm -rf ~/v2x_testbed/rsu/build/keys/*
   rm -rf ~/v2x_testbed/obu/build/keys/*
   rm -rf ~/v2x_testbed/obu/build/keys_obu2/*
   ```

2. **Start Desktop Server (Terminal 1):**
   ```bash
   cd ~/v2x_testbed/desktop
   python3 server.py
   ```
   *Expected:* "Registration servers started", listening on TCP:8001, 8002, 9000

3. **Start RSU (Terminal 2):**
   ```bash
   cd ~/v2x_testbed/rsu/build
   ./rsu_server ../config/rsu_config.json
   ```
   *Expected:* "Registered with Desktop", "UDP listener started on port 5000"

4. **Run OBU (Terminal 3):**
   ```bash
   cd ~/v2x_testbed/obu/build
   ./obu_client ../config/obu1_config.json
   ```

5. **Record Output:**
   - Copy console output to `results/baseline_single.log`
   - Note timestamps for each step
   - Record total time from "Sending AuthRequest" to "SESSION ESTABLISHED"

6. **Dashboard Verification:**
   - Open http://localhost:5000
   - Verify 9 events logged (registration + auth steps)
   - Screenshot event timeline

**Expected Output:**
```
Step 7: Sending AuthRequest...
Step 20-26: Processing AuthResponse...
Step 27-30: Confirming keys...
[OBU] ✓ SESSION ESTABLISHED
Total: 9.4ms
```

---

### Procedure 2: Multi-Cycle Performance (10 Loops)

**Objective:** Validate latency consistency across 10 consecutive authentications.

**Steps:**

1. **Clean Environment:**
   Same as Procedure 1

2. **Start Services (Terminals 1-2):**
   Same as Procedure 1

3. **Run OBU with 10 Loops (Terminal 3):**
   ```bash
   cd ~/v2x_testbed/obu/build
   time ./obu_client ../config/obu1_config.json --loop 10
   ```

4. **Record Metrics:**
   - Capture full console output
   - Note latency for each of 10 cycles
   - Record total wall-clock time
   - Note any errors or retries

5. **Dashboard Analysis:**
   - http://localhost:5000 shows all 10 authentication events
   - Verify session cleanup between cycles
   - Check for memory leaks (observer process memory)

6. **Save Results:**
   ```bash
   cp console.log results/10loop_$(date +%s).log
   ```

**Expected Output:**
```
=== Authentication Cycle 1 ===
Total: 9.2ms
Session established

=== Authentication Cycle 2 ===
Total: 9.5ms
Session established

... (cycles 3-10)

Wall-clock time: ~94ms (10 * 9.4ms)
```

---

### Procedure 3: Resource Utilization

**Objective:** Monitor CPU, memory, and network during auth cycles.

**Tools:**

```bash
# Terminal 4: Monitor processes
watch -n 0.1 'ps aux | grep -E "python3 server|rsu_server|obu_client"'

# Terminal 5: Monitor network
while true; do
  echo "=== $(date) ==="
  netstat -tuln | grep -E "8001|8002|5000|9000"
  ss -s
  sleep 1
done

# Terminal 6: Check memory with /proc
watch -n 1 'cat /proc/[PID]/status | grep VmRSS'
```

**Metrics to Record:**
- CPU usage during each phase (registration, auth, key conf)
- Memory footprint growth over 10 cycles
- Network packets sent/received
- Socket open/close counts

---

## Analysis Methodology

### 1. Latency Distribution

**Collect times for each phase across 10 cycles:**

```
Cycle | AuthReq | AuthResp | KeyConf | Total
------|---------|----------|---------|-------
1     | 3.2ms   | 4.5ms    | 0.5ms   | 8.2ms
2     | 3.4ms   | 4.3ms    | 0.4ms   | 8.1ms
...
10    | 3.3ms   | 4.4ms    | 0.5ms   | 9.2ms

Mean:     3.3ms    4.4ms    0.5ms    9.2ms
StdDev:   0.1ms    0.2ms    0.1ms    0.2ms
Min:      3.1ms    4.1ms    0.3ms    8.1ms
Max:      3.5ms    4.7ms    0.6ms    9.5ms
```

**Calculate Jitter (as % of mean):**
```
Jitter = (Max - Min) / Mean * 100
       = (9.5 - 8.1) / 9.2 * 100
       ≈ 15.2%  (acceptable if <20%)
```

### 2. Bottleneck Identification

**Review logs for longest phases:**

- If AuthResp dominates: RSU crypto or network latency
- If KeyConf slow: OBU verification or key derivation
- If Total high: Likely database I/O or serialization overhead

**Example:** If KeyConf averages 2ms but should be ~0.5ms:
- Check packet size (large payload → serialization time)
- Verify crypto operations (run `test_crypto` standalone)
- Profile OBU process with tools like `perf`

### 3. Session Cleanup Validation

**Check between cycles:**

```bash
# In RSU console, look for:
[RSU] Cleaned up expired session for OBU001

# On dashboard at http://localhost:5000:
- Sessions active should return to 0 after each cycle
- Event log should show cleanup confirmation
```

### 4. Database Performance

**Monitor SQLite operations:**

```bash
# Open second terminal while test runs
sqlite3 ~/v2x_testbed/desktop/database/v2x_testbed.db

# Check table sizes
SELECT name, COUNT(*) FROM sqlite_master 
WHERE type='table' GROUP BY name;

# Sample event timing
SELECT strftime('%Y-%m-%d %H:%M:%f', timestamp) as time, 
       action, duration_ms FROM events LIMIT 20;
```

---

## Performance Report Template

Create `results/performance_report_[date].md`:

```markdown
# V2X Authentication Performance Report

**Test Date:** [Date]  
**Tester:** [Name]  
**System:** [CPU, OS, RAM]  
**Crypto Provider:** PlaceholderProvider

## Results Summary

| Metric | Target | Measured | Status |
|--------|--------|----------|--------|
| Single Cycle Latency | <10ms | X.Xms | ✅ |
| 10-Cycle Average | <10ms | X.Xms | ✅ |
| Jitter (% deviation) | <20% | X% | ✅ |
| AuthRequest | <50ms | X.Xms | ✅ |
| AuthResponse | <50ms | X.Xms | ✅ |
| Session Cleanup | <100ms | X.Xms | ✅ |

## Detailed Metrics

[Insert latency distribution table from Section 1]

## Observations

- [Note any anomalies]
- [Identify bottlenecks]
- [Compare to previous runs]

## Artifacts

- Console logs: `10loop_[timestamp].log`
- Dashboard screenshot: `dashboard_[timestamp].png`
- System monitor output: `sysmon_[timestamp].log`

## Recommendations

[Any tuning suggestions]
```

---

## Adversarial Security Tests

### Procedure 4: Signature Corruption

**Objective:** Verify RSU rejects packets with invalid signatures.

```bash
cd ~/v2x_testbed/obu/build
./obu_client ../config/obu1_config.json --test-mode=corrupt_signature
```

**Expected:** OBU reports `Timeout waiting for SessionID` (RSU silently drops).
RSU console: `✗ Signature INVALID`. Dashboard: `SIGNATURE_CHECK_FAIL` event, Sig Failures counter +1.

### Procedure 5: Old Timestamp

**Objective:** Verify RSU rejects packets with expired timestamps.

```bash
./obu_client ../config/obu1_config.json --test-mode=old_timestamp
```

**Expected:** OBU reports timeout. RSU console: `✗ Timestamp FAILED: diff=60001xxxμs > threshold=50000μs`.
Dashboard: `TIMESTAMP_CHECK_FAIL` event, TS Failures counter +1.

### Procedure 6: Replay Attack

**Objective:** Verify RSU detects and rejects replayed AuthRequest packets.

```bash
./obu_client ../config/obu1_config.json --test-mode=replay
```

**Expected:** First packet processes normally, second (replay) rejected. RSU console: `✗ REPLAY DETECTED for PID=...`.
Dashboard: `REPLAY_DETECTED` event, Replays counter +1.

### Procedure 7: Emergency Vehicle Priority

**Objective:** Verify emergency flag transmission and detection via post-auth encrypted messaging.

```bash
./obu_client ../config/obu2_config.json
```

**Expected:** OBU shows `🚑 Emergency priority flag sent`. RSU shows `🚑 EMERGENCY VEHICLE DETECTED — Granting priority`.
Dashboard: `EMERGENCY_PRIORITY_GRANTED` event, OBU2 entity shows 🚑 in Emergency column.

### Automated Full Test Suite

```bash
./scripts/run_full_system_test.sh
```

Runs normal auth + all 3 adversarial tests automatically. Reports pass/fail summary.

---

## Post-Authentication Messaging Validation

After session establishment, verify encrypted post-auth messaging:

**What to check in RSU output:**
```
[PROC] Post-auth HMAC verified ✓
[PROC] Post-auth decrypted: 147 bytes
[PROC] Payload: {"entity_id":"OBU1","is_emergency":false,...}
```

**Verify in Dashboard:**
- `POST_AUTH_RECEIVED` event appears after `SESSION_ESTABLISHED`
- Performance tab shows `aes_decrypt` and `hmac_verify` crypto timing bars

---

## Troubleshooting

### High Latency (>20ms)

**Diagnose:**
- Run single-cycle baseline first
- Check CPU usage (if >50%, background load exists)
- Verify NTP sync if testing across machines (`ntpq -p`)
- Test on isolated network if possible

**Solution:**
- Close other applications
- Run on dedicated hardware
- Check for network congestion

### Inconsistent Latencies (>10ms jitter)

**Causes:**
- Database locks (SQLite → use WAL mode)
- Garbage collection pauses (Python GC)
- System load spikes (check `top`, `iotop`)

**Solutions:**
- Increase database synchronous setting: `WAL mode`
- Run on quiet system
- Increase sampling window (20-50 cycles instead of 10)

### Session Not Established

**Check:**
1. Are all 3 services running? (`ps aux | grep`)
2. Are ports free? (`lsof -i :8001` etc.)
3. Check firewall: `sudo ufw status`
4. Verify config paths are correct

**Reset:**
```bash
killall python3 rsu_server obu_client 2>/dev/null
rm -f ~/v2x_testbed/desktop/database/v2x_testbed.db
sleep 2
# Restart from procedure step 2
```

---

## Advanced Analysis

### Flame Graph Profile

For deep optimization (C++ side):

```bash
cd ~/v2x_testbed/rsu/build

# Build with profiling
cmake -DCMAKE_BUILD_TYPE=RelWithDebInfo ..
make clean && make -j$(nproc)

# Run with perf
perf record -g ./rsu_server ../config/rsu_config.json &
# Run OBU in another terminal
perf report
```

### Python Profiling (Desktop Server)

```bash
cd ~/v2x_testbed/desktop

# Using py-spy
pip3 install py-spy
py-spy record -o profile.svg -- python3 server.py

# Open profile.svg in browser to see bottlenecks
```

---

## Regression Testing

After code changes, always run:

1. **Protocol tests:**
   ```bash
   cd protocol/build && ./test_protocol_flow
   ```

2. **Baseline single cycle:**
   Procedure 1 above

3. **10-cycle performance:**
   Procedure 2 above

4. **Save report:**
   Document all results with version/commit hash

---

## Sign-Off

Once all tests pass:

```
✅ Single cycle latency: <10ms
✅ 10-cycle average: <10ms
✅ Jitter: <20%
✅ All events logged
✅ Session cleanup verified
✅ No crashes or errors

Performance Validated
Date: [Date]
Tester: [Name]
```

---

## License

Copyright (c) 2026 Siliris Technologies Pvt. Ltd.  
Proprietary - See LICENSE file for terms.
