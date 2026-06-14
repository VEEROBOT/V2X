#!/usr/bin/env bash
# v2x_robot_log — extract a compact status snapshot from the robot's systemd journal
# Run on the Pi (car or ambulance) to produce a shareable one-page log.
#
# Install: sudo bash setup.sh [car|ambulance]  (adds to /usr/local/bin/v2x_robot_log)
#
# Usage:
#   v2x_robot_log            # auto-detect role from running service
#   v2x_robot_log car
#   v2x_robot_log ambulance
#   v2x_robot_log > ~/v2x_log.txt

ROLE="${1:-}"

# Auto-detect role if not given
if [ -z "$ROLE" ]; then
    if systemctl is-active --quiet v2x_ambulance 2>/dev/null; then
        ROLE="ambulance"
    elif systemctl is-active --quiet v2x_car 2>/dev/null; then
        ROLE="car"
    else
        # Try to detect from last active
        if journalctl -u v2x_ambulance -n 1 --no-pager -q 2>/dev/null | grep -q .; then
            ROLE="ambulance"
        else
            ROLE="car"
        fi
    fi
fi

SERVICE="v2x_${ROLE}"
HOST=$(hostname)
NOW=$(date '+%Y-%m-%d %H:%M:%S')

W=62
echo "$(printf '=%.0s' $(seq 1 $W))"
echo "  V2X ROBOT LOG — $HOST  ($ROLE)"
echo "  Generated: $NOW"
echo "$(printf '=%.0s' $(seq 1 $W))"

# --- Service status ---
echo ""
echo "SERVICE STATUS:"
STATUS=$(systemctl show "$SERVICE" --property=ActiveState,SubState,ExecMainPID,Result --value 2>/dev/null | paste - - - -)
SVC_STATE=$(systemctl is-active "$SERVICE" 2>/dev/null)
echo "  $SERVICE: $SVC_STATE"
SINCE=$(systemctl show "$SERVICE" --property=ActiveEnterTimestamp --value 2>/dev/null)
[ -n "$SINCE" ] && echo "  Running since: $SINCE"

# --- Key startup events (since last service start) ---
echo ""
echo "STARTUP EVENTS:"
journalctl -u "$SERVICE" -n 200 --no-pager -o cat 2>/dev/null | grep -E \
    "ROBOT READY|Started v2x|Stopped v2x|Failed|error|ERROR|Camera:|Joystick:|OBU binary|OBU mode|OBU process|V2X bridge|Starting OBU|Registration complete|Bound to|SESSION ESTABLISHED|EMERGENCY|entity_id|is_emergency" \
    | tail -30 | sed 's/^/  /'

# --- OBU authentication events (last 2 minutes of activity) ---
echo ""
echo "RECENT OBU EVENTS:"
journalctl -u "$SERVICE" -n 500 --no-pager -o cat 2>/dev/null | grep -E \
    "\[AUTH\]|\[REG\]|\[UDP\]|Emergency V2X|Emergency priority|OBU stopped|OBU session ended|restarting in" \
    | grep -v "Timing Breakdown\|pid_gen\|encapsulate\|verify_sig\|sign \|derive_key\|hmac_kc1" \
    | tail -20 | sed 's/^/  /'

# --- Errors ---
echo ""
echo "ERRORS / WARNINGS:"
ERRS=$(journalctl -u "$SERVICE" -n 300 --no-pager -o cat 2>/dev/null | grep -iE \
    "error|fail|traceback|exception|killed|permission denied|SIGKILL|Cannot|Unable" \
    | grep -v "Failed to open /dev/dma_heap\|Unsupported V4L2\|camera_manager\|configuration has been adjusted" \
    | tail -10)
if [ -n "$ERRS" ]; then
    echo "$ERRS" | sed 's/^/  /'
else
    echo "  (none) ✓"
fi

# --- OBU config snapshot ---
WORKING_DIR=$(systemctl show "$SERVICE" --property=WorkingDirectory --value 2>/dev/null)
WORKING_DIR="${WORKING_DIR:-/home/veerobot/projects/V2X/robot_python}"
OBU_CONFIG="$(dirname "$WORKING_DIR")/v2x_testbed/obu/config/obu_local.json"
echo ""
echo "OBU CONFIG ($OBU_CONFIG):"
if [ -f "$OBU_CONFIG" ]; then
    python3 -c "
import json, sys
try:
    c = json.load(open('$OBU_CONFIG'))
    keys = ['entity_id','udp_listen_port','rsu_ip','is_emergency','key_directory']
    for k in keys:
        print(f'  {k}: {c.get(k,\"?\")}'  )
except Exception as e:
    print(f'  read error: {e}')
"
else
    echo "  (file not found)"
fi

echo ""
echo "$(printf '=%.0s' $(seq 1 $W))"
