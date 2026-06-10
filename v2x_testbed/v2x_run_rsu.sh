#!/usr/bin/env bash
# v2x_run_rsu — start RSU server
# Run this in Terminal 2 AFTER v2x_run_desktop is up.
#
# Add to PATH (run once on laptop):
#   echo 'export PATH="$PATH:$HOME/V2X/v2x_testbed"' >> ~/.bashrc && source ~/.bashrc

set -e
TESTBED="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
RSU_BIN="$TESTBED/rsu/build/rsu_server"
RSU_CFG="$TESTBED/rsu/config/rsu_config.json"

if [ ! -f "$RSU_BIN" ]; then
    echo "ERROR: RSU binary not found: $RSU_BIN"
    echo "Build it: cd $TESTBED/rsu/build && cmake .. && make -j\$(nproc)"
    exit 1
fi

echo "[v2x] Starting RSU..."
"$RSU_BIN" "$RSU_CFG"
