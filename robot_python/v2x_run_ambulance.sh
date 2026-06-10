#!/usr/bin/env bash
# v2x_run_ambulance — clear OBU keys and restart ambulance service
# Install: sudo bash setup.sh ambulance   (adds to /usr/local/bin/v2x_run_ambulance)

WORKING_DIR=$(systemctl show v2x_ambulance --property=WorkingDirectory --value 2>/dev/null)
WORKING_DIR="${WORKING_DIR:-/home/veerobot/projects/V2X/robot_python}"
KEY_DIR="${WORKING_DIR}/keys_$(hostname)"

echo "[v2x] Clearing OBU keys: $KEY_DIR"
rm -rf "$KEY_DIR"

echo "[v2x] Restarting v2x_ambulance..."
sudo systemctl restart v2x_ambulance

echo "[v2x] Logs (Ctrl+C to exit):"
sudo journalctl -fu v2x_ambulance
