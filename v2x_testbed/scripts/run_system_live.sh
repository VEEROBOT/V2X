#!/bin/bash

set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT_DIR/logs"
mkdir -p "$LOG_DIR"

DESKTOP_LOG="$LOG_DIR/desktop_live.log"
RSU_LOG="$LOG_DIR/rsu_live.log"
OBU_LOG="$LOG_DIR/obu_live.log"

echo "==========================================="
echo "        V2X LIVE SYSTEM MODE"
echo "==========================================="

# ------------------------------------------
# Kill old processes
# ------------------------------------------
echo "[1] Stopping previous instances..."
pkill -f server.py || true
pkill -f rsu_server || true
pkill -f obu_client || true
sleep 1

# ------------------------------------------
# Clean state (fresh start)
# ------------------------------------------
echo "[2] Cleaning DB and keys..."
rm -f "$ROOT_DIR/desktop/database/v2x_testbed.db"
rm -f "$ROOT_DIR/desktop/database/master_secret.bin"

rm -rf "$ROOT_DIR/rsu/build/keys" 2>/dev/null || true
rm -rf "$ROOT_DIR/obu/build/keys" 2>/dev/null || true
rm -rf "$ROOT_DIR/obu/build/keys_obu2" 2>/dev/null || true

# ------------------------------------------
# Build RSU
# ------------------------------------------
echo "[3] Building RSU..."

cd "$ROOT_DIR/rsu"
mkdir -p build
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release > /dev/null
make -j$(nproc) > /dev/null

# ------------------------------------------
# Build OBU
# ------------------------------------------
echo "[4] Building OBU..."

cd "$ROOT_DIR/obu"
mkdir -p build
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release > /dev/null
make -j$(nproc) > /dev/null

# ------------------------------------------
# Start Desktop
# ------------------------------------------
echo "[5] Starting Desktop..."
cd "$ROOT_DIR/desktop"
python3 server.py > "$DESKTOP_LOG" 2>&1 &
DESKTOP_PID=$!

echo "    Waiting for dashboard..."
sleep 3

# ------------------------------------------
# Start RSU
# ------------------------------------------
echo "[6] Starting RSU..."
cd "$ROOT_DIR/rsu/build"
./rsu_server ../config/rsu_config.json > "$RSU_LOG" 2>&1 &
RSU_PID=$!

sleep 3

# ------------------------------------------
# Start OBU (single normal auth)
# ------------------------------------------
echo "[7] Starting OBU..."
cd "$ROOT_DIR/obu/build"
./obu_client ../config/obu1_config.json > "$OBU_LOG" 2>&1 &

echo ""
echo "==========================================="
echo "   LIVE SYSTEM RUNNING"
echo "==========================================="
echo "Dashboard: http://localhost:5000"
echo ""
echo "Logs:"
echo "  Desktop → $DESKTOP_LOG"
echo "  RSU     → $RSU_LOG"
echo "  OBU     → $OBU_LOG"
echo ""
echo "Press Ctrl+C to stop."
echo ""

# ------------------------------------------
# Graceful shutdown on Ctrl+C
# ------------------------------------------
trap 'echo ""; echo "Stopping system..."; kill $DESKTOP_PID 2>/dev/null; kill $RSU_PID 2>/dev/null; pkill -f obu_client 2>/dev/null; exit 0' INT

wait