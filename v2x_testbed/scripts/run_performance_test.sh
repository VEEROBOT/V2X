#!/bin/bash

################################################################################
# V2X Authentication Testbed — Automated Performance Test Script
#
# File: run_performance_test.sh
# Module: Testing & Performance Validation
#
# Purpose:
#     Automates multi-loop performance testing. Cleans environment, starts all
#     services, runs 10 authentication cycles, collects metrics, and generates
#     performance report.
#
# Author(s): Praveen Kumar
# Company: Siliris Technologies Pvt. Ltd
# Created: 15th February 2026
# Version: 1.1
#
# Usage:
#     ./scripts/run_performance_test.sh [num_loops] [crypto_provider]
#
#     num_loops: Number of authentication cycles (default: 10)
#     crypto_provider: PlaceholderProvider or LatticeProvider (default: PlaceholderProvider)
#
# Example:
#     ./scripts/run_performance_test.sh 10 PlaceholderProvider
#     ./scripts/run_performance_test.sh 20
#
# License:
#     Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
#     Proprietary - See LICENSE file for terms and conditions.
#
################################################################################

set -e

# Configuration
TESTBED_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../" && pwd)"
RESULTS_DIR="${TESTBED_ROOT}/results"
LOOPS=${1:-10}
CRYPTO_PROVIDER=${2:-PlaceholderProvider}
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
REPORT_FILE="${RESULTS_DIR}/performance_report_${TIMESTAMP}.md"

# Colors for output (using printf-compatible escape sequences)
GREEN='\x1b[0;32m'
BLUE='\x1b[0;34m'
YELLOW='\x1b[1;33m'
RED='\x1b[0;31m'
NC='\x1b[0m' # No Color

# Functions
print_header() {
    printf "${BLUE}================================${NC}\n"
    printf "${BLUE}%s${NC}\n" "$1"
    printf "${BLUE}================================${NC}\n"
}

print_status() {
    printf "${GREEN}✓${NC} %s\n" "$1"
}

print_error() {
    printf "${RED}✗${NC} %s\n" "$1"
}

print_info() {
    printf "${YELLOW}ℹ${NC} %s\n" "$1"
}

cleanup_processes() {
    print_info "Stopping any running processes..."
    pkill -f "python3 server.py" || true
    pkill -f "rsu_server" || true
    pkill -f "obu_client" || true
    sleep 1
}

cleanup_state() {
    print_status "Cleaning up old state..."
    rm -f "${TESTBED_ROOT}/desktop/database/v2x_testbed.db"
    rm -f "${TESTBED_ROOT}/desktop/database/master_secret.bin"
    rm -rf "${TESTBED_ROOT}/rsu/build/keys"/*
    rm -rf "${TESTBED_ROOT}/obu/build/keys"/*
    rm -rf "${TESTBED_ROOT}/obu/build/keys_obu2"/*
    mkdir -p "${TESTBED_ROOT}/rsu/build/keys"
    mkdir -p "${TESTBED_ROOT}/obu/build/keys"
    mkdir -p "${TESTBED_ROOT}/obu/build/keys_obu2"
    print_status "State cleaned"
}

verify_builds() {
    print_status "Verifying builds..."
    
    [ -f "${TESTBED_ROOT}/desktop/server.py" ] || { print_error "Desktop server not found"; exit 1; }
    [ -x "${TESTBED_ROOT}/rsu/build/rsu_server" ] || { print_error "RSU server not built"; exit 1; }
    [ -x "${TESTBED_ROOT}/obu/build/obu_client" ] || { print_error "OBU client not built"; exit 1; }
    
    print_status "All builds verified"
}

start_desktop() {
    print_status "Starting Desktop server..."
    cd "${TESTBED_ROOT}/desktop"
    python3 server.py > "${RESULTS_DIR}/desktop_${TIMESTAMP}.log" 2>&1 &
    DESKTOP_PID=$!
    sleep 2
    
    if ! kill -0 $DESKTOP_PID 2>/dev/null; then
        print_error "Desktop server failed to start"
        cat "${RESULTS_DIR}/desktop_${TIMESTAMP}.log"
        exit 1
    fi
    print_status "Desktop server running (PID: $DESKTOP_PID)"
}

start_rsu() {
    print_status "Starting RSU server..."
    cd "${TESTBED_ROOT}/rsu/build"
    ./rsu_server ../config/rsu_config.json > "${RESULTS_DIR}/rsu_${TIMESTAMP}.log" 2>&1 &
    RSU_PID=$!
    sleep 2
    
    if ! kill -0 $RSU_PID 2>/dev/null; then
        print_error "RSU server failed to start"
        cat "${RESULTS_DIR}/rsu_${TIMESTAMP}.log"
        cleanup_processes
        exit 1
    fi
    print_status "RSU server running (PID: $RSU_PID)"
}

run_obu_test() {
    print_status "Running OBU authentication (${LOOPS} loops)..."
    cd "${TESTBED_ROOT}/obu/build"
    
    OBU_OUTPUT="${RESULTS_DIR}/obu_${TIMESTAMP}.log"
    
    if ./obu_client ../config/obu1_config.json --loop ${LOOPS} > "$OBU_OUTPUT" 2>&1; then
        print_status "OBU test completed successfully"
        cat "$OBU_OUTPUT"
    else
        print_error "OBU test failed"
        cat "$OBU_OUTPUT"
        cleanup_processes
        exit 1
    fi
}

generate_report() {
    print_status "Generating performance report..."
    
    cat > "$REPORT_FILE" << 'REPORT_EOF'
# V2X Authentication Performance Report

**Generated:** TIMESTAMP_PLACEHOLDER
**Test Loops:** LOOPS_PLACEHOLDER
**Crypto Provider:** CRYPTO_PLACEHOLDER
**System:** SYSTEM_PLACEHOLDER

## Summary

- OBU Loops: LOOPS_PLACEHOLDER
- Expected Cycles: LOOPS_PLACEHOLDER
- Target Latency: <10ms per cycle
- Target Total: <10ms * LOOPS_PLACEHOLDER = ~TOTAL_MS ms

## Results

### Logs Location

- Desktop Server: `results/desktop_TIMESTAMP_PLACEHOLDER.log`
- RSU Server: `results/rsu_TIMESTAMP_PLACEHOLDER.log`
- OBU Client: `results/obu_TIMESTAMP_PLACEHOLDER.log`

### Key Metrics

Extracted from logs - see raw logs above for detailed timing breakdown.

Key lines to look for in OBU output:
```
Total X.Xms — Session established
```

## Analysis

Calculate average, min, max, and standard deviation from per-cycle latencies.

## Artifacts

- Full logs: See results directory above
- Console outputs: Captured in results/ directory
- Report generated: REPORT_PLACEHOLDER

## Next Steps

1. Review raw logs for anomalies
2. Calculate latency distribution
3. Check for consistent performance
4. Identify any bottlenecks

See `docs/PERFORMANCE_TESTING.md` for detailed analysis methodology.

---
**License:** Copyright (c) 2026 Siliris Technologies Pvt. Ltd. Proprietary.
REPORT_EOF

    # Replace placeholders in report
    sed -i "s|TIMESTAMP_PLACEHOLDER|$(date)|g" "$REPORT_FILE"
    sed -i "s|LOOPS_PLACEHOLDER|$LOOPS|g" "$REPORT_FILE"
    sed -i "s|CRYPTO_PLACEHOLDER|$CRYPTO_PROVIDER|g" "$REPORT_FILE"
    sed -i "s|SYSTEM_PLACEHOLDER|$(uname -a)|g" "$REPORT_FILE"
    sed -i "s|TOTAL_MS|$((LOOPS * 10))|g" "$REPORT_FILE"
    sed -i "s|REPORT_PLACEHOLDER|$REPORT_FILE|g" "$REPORT_FILE"

    print_info "Report saved to: $REPORT_FILE"
}

collect_system_metrics() {
    print_status "Collecting system metrics..."
    
    SYSINFO_FILE="${RESULTS_DIR}/sysinfo_${TIMESTAMP}.txt"
    
    {
        echo "System Information"
        echo "=================="
        echo ""
        echo "CPU:"
        lscpu | head -10
        echo ""
        echo "Memory:"
        free -h
        echo ""
        echo "Linux Version:"
        uname -a
    } > "$SYSINFO_FILE"
    
    print_info "System info saved to: $SYSINFO_FILE"
}

show_running_services() {
    print_status "Running services:"
    printf "\n"
    ps aux | grep -E 'python3 server|rsu_server' | grep -v grep || true
    printf "\n"
}

main() {
    print_header "V2X Authentication Performance Test"
    
    printf "Test Configuration:\n"
    printf "  Loops: %s\n" "$LOOPS"
    printf "  Crypto: %s\n" "$CRYPTO_PROVIDER"
    printf "  Results Dir: %s\n" "$RESULTS_DIR"
    printf "\n"
    
    # Validate inputs
    if ! [[ $LOOPS =~ ^[0-9]+$ ]] || [ $LOOPS -lt 1 ]; then
        print_error "Invalid loop count. Must be positive integer."
        exit 1
    fi
    
    # Setup
    mkdir -p "$RESULTS_DIR"
    cleanup_processes
    
    print_header "Phase 1: Environment Setup"
    cleanup_state
    verify_builds
    collect_system_metrics
    
    print_header "Phase 2: Start Services"
    start_desktop
    start_rsu
    
    print_header "Phase 3: Run Authentication Test"
    run_obu_test
    
    print_header "Phase 4: Report Generation"
    generate_report
    show_running_services
    
    print_header "Test Complete"
    printf "${GREEN}✓ Performance test successfully completed!${NC}\n"
    printf "\n"
    printf "Results saved to: %s\n" "$RESULTS_DIR"
    printf "Report: %s\n" "$REPORT_FILE"
    printf "\n"
    printf "${BLUE}────────────────────────────────────────${NC}\n"
    printf "${BLUE}DASHBOARD STILL RUNNING - VIEW RESULTS${NC}\n"
    printf "${BLUE}────────────────────────────────────────${NC}\n"
    printf "\n"
    printf "${GREEN}Dashboard URL:${NC} http://localhost:5000\n"
    printf "\n"
    printf "The following services remain running:\n"
    printf "  • Desktop Server (HTTP:5000, Log Receiver TCP:9000)\n"
    printf "  • RSU Server (UDP:5000)\n"
    printf "\n"
    printf "Open http://localhost:5000 in your browser to:\n"
    printf "  ✓ View all %s authentication events\n" "$LOOPS"
    printf "  ✓ Review session lifecycle\n"
    printf "  ✓ Analyze event timing\n"
    printf "\n"
    printf "When done reviewing, stop services with:\n"
    printf "  ${YELLOW}pkill -f 'python3 server.py'${NC}\n"
    printf "  ${YELLOW}pkill -f 'rsu_server'${NC}\n"
    printf "\n"
    printf "Or manually review logs:\n"
    printf "  - OBU cycles: ${GREEN}cat${NC} %s/obu_%s.log\n" "$RESULTS_DIR" "$TIMESTAMP"
    printf "  - RSU events: ${GREEN}cat${NC} %s/rsu_%s.log\n" "$RESULTS_DIR" "$TIMESTAMP"
    printf "  - Desktop log: ${GREEN}cat${NC} %s/desktop_%s.log\n" "$RESULTS_DIR" "$TIMESTAMP"
}

# Trap to handle interruption gracefully
trap 'print_error "Test interrupted"; print_info "Services still running - manually close them when done"; exit 1' INT TERM

# Run main
main "$@"
