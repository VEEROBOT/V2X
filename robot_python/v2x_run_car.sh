#!/usr/bin/env bash
# v2x_run_car — regenerate OBU config, clear keys, restart car service
# Install: sudo bash setup.sh car   (adds to /usr/local/bin/v2x_run_car)

WORKING_DIR=$(systemctl show v2x_car --property=WorkingDirectory --value 2>/dev/null)
WORKING_DIR="${WORKING_DIR:-/home/veerobot/projects/V2X/robot_python}"
REPO_DIR="$(dirname "$WORKING_DIR")"
OBU_DIR="$REPO_DIR/v2x_testbed/obu"
OBU_CONFIG="$OBU_DIR/config/obu_local.json"
KEY_DIR="${WORKING_DIR}/keys_$(hostname)"

# Derive entity_id from hostname (same transform as setup.sh)
MY_HOSTNAME=$(hostname)
ENTITY_ID=$(echo "$MY_HOSTNAME" | tr '[:lower:]-' '[:upper:]_' | tr -cd 'A-Z0-9_')

# Read RSU/desktop IPs from the reference config
RSU_IP=$(python3 -c "import json; c=json.load(open('$OBU_DIR/config/obu1_config.json')); print(c['rsu_ip'])" 2>/dev/null || echo "192.168.0.103")
DESKTOP_IP=$(python3 -c "import json; c=json.load(open('$OBU_DIR/config/obu1_config.json')); print(c['desktop_ip'])" 2>/dev/null || echo "192.168.0.103")

echo "[v2x] Regenerating OBU config: entity_id=${ENTITY_ID}  is_emergency=false"
sudo tee "$OBU_CONFIG" > /dev/null << OBUEOF
{
    "entity_id": "${ENTITY_ID}",
    "obu_ip": "0.0.0.0",
    "udp_listen_port": 5003,
    "rsu_ip": "${RSU_IP}",
    "rsu_port": 5000,
    "desktop_ip": "${DESKTOP_IP}",
    "desktop_reg_port": 8001,
    "is_emergency": false,
    "delta_ts_ms": 500,
    "crypto_provider": "placeholder",
    "key_directory": "./keys_${MY_HOSTNAME}/"
}
OBUEOF

echo "[v2x] Clearing OBU keys: $KEY_DIR"
rm -rf "$KEY_DIR"

echo "[v2x] Killing any stale main_car.py processes..."
sudo pkill -f "main_car.py" 2>/dev/null || true
sleep 0.5

echo "[v2x] Restarting v2x_car..."
sudo systemctl restart v2x_car

echo "[v2x] Logs (Ctrl+C to exit):"
sudo journalctl -fu v2x_car
