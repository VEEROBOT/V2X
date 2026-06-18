#!/usr/bin/env bash
# v2x_run_desktop — fresh-start Desktop server (clears all sessions)
# Run this FIRST on the laptop, then run v2x_run_rsu.sh on the RSU Pi.
#
# Add to PATH (run once on laptop):
#   echo 'export PATH="$PATH:$HOME/V2X/v2x_testbed"' >> ~/.bashrc && source ~/.bashrc

set -e
TESTBED="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"

echo "[v2x] Clearing sessions..."
rm -f  "$TESTBED/desktop/database/v2x_testbed.db"
rm -f  "$TESTBED/desktop/database/master_secret.bin"

echo "[v2x] Starting Desktop server..."
echo "[v2x] Dashboard: http://localhost:5000"
echo ""
cd "$TESTBED/desktop"
python3 server.py
