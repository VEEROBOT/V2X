#!/bin/bash

set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR=$ROOT_DIR/logs
mkdir -p $LOG_DIR

DESKTOP_LOG=$LOG_DIR/desktop.log
RSU_LOG=$LOG_DIR/rsu.log
OBU_LOG=$LOG_DIR/obu.log

echo "==========================================="
echo " V2X FULL SYSTEM SECURITY TEST SUITE"
echo "==========================================="

TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# ------------------------------------------
# Clean previous processes
# ------------------------------------------
pkill -f server.py || true
pkill -f rsu_server || true
pkill -f obu_client || true
sleep 1

# ------------------------------------------
# Clean state
# ------------------------------------------
echo "[1] Cleaning DB and keys..."
rm -f $ROOT_DIR/desktop/database/v2x_testbed.db
rm -f $ROOT_DIR/desktop/database/master_secret.bin
rm -rf $ROOT_DIR/rsu/build/keys/*
rm -rf $ROOT_DIR/obu/build/keys/*
rm -rf $ROOT_DIR/obu/build/keys_obu2/*

# ------------------------------------------
# Build everything
# ------------------------------------------
# ------------------------------------------
# Build RSU
# ------------------------------------------
echo "[2] Building RSU..."

cd $ROOT_DIR/rsu
mkdir -p build
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release > /dev/null
make -j$(nproc) > /dev/null

# ------------------------------------------
# Build OBU
# ------------------------------------------
echo "[3] Building OBU..."

cd $ROOT_DIR/obu
mkdir -p build
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release > /dev/null
make -j$(nproc) > /dev/null

# ------------------------------------------
# Start Desktop
# ------------------------------------------
echo "[4] Starting Desktop..."
cd $ROOT_DIR/desktop
python3 server.py > $DESKTOP_LOG 2>&1 &
DESKTOP_PID=$!
sleep 3

# ------------------------------------------
# Start RSU
# ------------------------------------------
echo "[5] Starting RSU..."
cd $ROOT_DIR/rsu/build
./rsu_server ../config/rsu_config.json > $RSU_LOG 2>&1 &
RSU_PID=$!
sleep 3

# ------------------------------------------
# Helper function
# ------------------------------------------
run_test() {
    MODE=$1
    EXPECT_SUCCESS=$2

    TOTAL_TESTS=$((TOTAL_TESTS+1))

    echo ""
    echo "-------------------------------------------"
    echo "Running test: $MODE"
    echo "-------------------------------------------"

    cd $ROOT_DIR/obu/build

    if [ "$MODE" == "normal" ]; then
        ./obu_client ../config/obu1_config.json > $OBU_LOG 2>&1 || true
    else
        ./obu_client ../config/obu1_config.json --test-mode=$MODE > $OBU_LOG 2>&1 || true
    fi

    TEST_PASSED=false

    if [ "$EXPECT_SUCCESS" == "true" ]; then
        if grep -q "SESSION ESTABLISHED SUCCESSFULLY" $OBU_LOG; then
            echo "✅ $MODE: PASS"
            TEST_PASSED=true
        else
            echo "❌ $MODE: FAIL"
        fi
    else
        if grep -q "FAILED" $OBU_LOG; then
            echo "✅ $MODE: PASS (correctly failed)"
            TEST_PASSED=true
        else
            echo "❌ $MODE: FAIL (unexpected success)"
        fi
    fi

    if [ "$TEST_PASSED" == "true" ]; then
        PASSED_TESTS=$((PASSED_TESTS+1))
    else
        FAILED_TESTS=$((FAILED_TESTS+1))
    fi
}

# ------------------------------------------
# Run Tests
# ------------------------------------------
run_test "normal" true
run_test "corrupt_signature" false
run_test "old_timestamp" false
run_test "replay" false

# ------------------------------------------
# Verify Replay Detection in RSU log
# ------------------------------------------
echo ""
echo "Checking RSU replay detection..."

if grep -q "REPLAY DETECTED" $RSU_LOG; then
    echo "✅ Replay detection logged"
else
    echo "❌ Replay detection NOT logged"
fi

# ------------------------------------------
# Cleanup
# ------------------------------------------
echo ""
echo "Cleaning up processes..."
kill $DESKTOP_PID || true
kill $RSU_PID || true
pkill -f obu_client || true

echo ""
echo "==========================================="
echo "              TEST SUMMARY"
echo "==========================================="
echo "Total Tests : $TOTAL_TESTS"
echo "Passed      : $PASSED_TESTS"
echo "Failed      : $FAILED_TESTS"

if [ "$FAILED_TESTS" -eq 0 ]; then
    echo "Overall     : ✅ ALL TESTS PASSED"
else
    echo "Overall     : ❌ SOME TESTS FAILED"
fi
echo "==========================================="

echo ""
echo "==========================================="
echo " TEST SUITE COMPLETE"
echo " Logs available in: $LOG_DIR"
echo "==========================================="