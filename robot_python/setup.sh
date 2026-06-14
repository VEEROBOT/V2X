#!/usr/bin/env bash
# V2X Robot Setup — Ubuntu 24.04 on Raspberry Pi 5
# Usage:  bash setup.sh car        (default)
#         bash setup.sh ambulance
#
# What this does:
#   1. Installs system packages (libcamera 0.5, picamera2, pygame, etc.)
#   2. Adds Raspberry Pi apt repo for libcamera 0.5
#   3. Builds Python 3.12 libcamera bindings from source (Pi 5 needs this)
#   4. Creates Python venv with system-site-packages
#   5. Installs pip requirements
#   6. Patches picamera2 DrmPreview (headless fix)
#   7. Configures /boot/firmware/config.txt (camera + UART)
#   8. Configures /boot/firmware/cmdline.txt (removes serial console)
#   9. Adds user to dialout group
#  10. Builds OBU binary (V2X authentication)
#  11. Installs CLI commands (v2x_run_car, v2x_run_ambulance)
#  12. Installs and enables systemd service
#
# After running: sudo reboot

set -e
ROLE="${1:-car}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
VENV="$SCRIPT_DIR/.venv"
USER_HOME=$(eval echo "~$SUDO_USER")
REAL_USER="${SUDO_USER:-$USER}"

if [[ $EUID -ne 0 ]]; then
    echo "Run with sudo:  sudo bash setup.sh $ROLE"
    exit 1
fi

if [[ "$ROLE" != "car" && "$ROLE" != "ambulance" ]]; then
    echo "Usage: sudo bash setup.sh [car|ambulance]"
    exit 1
fi

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   V2X Robot Setup — role: $ROLE"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── 1. Base packages (from Ubuntu default repos) ────────────────────────────
echo "[1/11] Installing base packages..."
apt-get update -qq
apt-get install -y -qq \
    python3-pip python3-venv python3-pygame \
    libcap-dev joystick \
    cmake libssl-dev build-essential \
    git curl gpg

# ── 2. Raspberry Pi apt repo + picamera2 + libcamera ────────────────────────
echo "[2/11] Adding Raspberry Pi apt repo..."
if [ ! -f /usr/share/keyrings/raspberrypi-archive-keyring.gpg ]; then
    curl -fsSL https://archive.raspberrypi.com/debian/raspberrypi.gpg.key \
        | gpg --dearmor \
        | tee /usr/share/keyrings/raspberrypi-archive-keyring.gpg > /dev/null
fi
if [ ! -f /etc/apt/sources.list.d/raspi.list ]; then
    echo "deb [signed-by=/usr/share/keyrings/raspberrypi-archive-keyring.gpg] https://archive.raspberrypi.com/debian/ bookworm main" \
        > /etc/apt/sources.list.d/raspi.list
fi
# Pin: RPi repo wins only for camera packages; Ubuntu keeps everything else.
# Without this, libcamera0.5 from bookworm conflicts with Ubuntu 24.04 packages.
cat > /etc/apt/preferences.d/90-raspi-camera << 'PINEOF'
Package: libcamera* python3-picamera2 python3-libcamera rpicam-apps*
Pin: origin archive.raspberrypi.com
Pin-Priority: 600

Package: *
Pin: origin archive.raspberrypi.com
Pin-Priority: 1
PINEOF
apt-get update -qq
apt-get install -f -y -qq                                      # fix any pre-existing broken deps
# libcamera0.5 and libcamera-ipa from RPi repo; skip python3-picamera2 and
# libcamera-tools — they require python3<3.12 / libjpeg62-turbo (Debian-only).
# picamera2 is installed via pip in step 5 and works fine with Python 3.12.
apt-get install -y -qq --allow-change-held-packages \
    libcamera0.5 libcamera-ipa

# ── 3. Build Python 3.12 libcamera bindings ─────────────────────────────────
LIBCAM_SO=/usr/lib/aarch64-linux-gnu/python3.12/site-packages/libcamera/_libcamera.so
if [ ! -f "$LIBCAM_SO" ]; then
    echo "[3/11] Building Python 3.12 libcamera bindings (takes ~5-8 min)..."
    apt-get install -y -qq meson ninja-build pybind11-dev python3-ply libcamera-dev
    BUILD_DIR=$(mktemp -d)
    git clone --depth 1 --branch v0.5.2+rpt20250903 \
        https://github.com/raspberrypi/libcamera.git "$BUILD_DIR"
    pushd "$BUILD_DIR" > /dev/null
    meson setup build \
        -Dpycamera=enabled -Dcam=disabled -Dgstreamer=disabled \
        -Dipas=[] -Dpipelines=[] -Dlc-compliance=disabled \
        -Ddocumentation=disabled -Dtracing=disabled
    TARGET=$(ninja -C build -t targets all 2>/dev/null | grep '_libcamera.cpython.*\.so:' | head -1 | cut -d: -f1)
    TARGET="${TARGET:-src/py/libcamera/pylibcamera}"
    cd build && ninja "$TARGET"
    SITE_DIR=/usr/lib/aarch64-linux-gnu/python3.12/site-packages/libcamera
    mkdir -p "$SITE_DIR"
    cp src/py/libcamera/_libcamera*.so "$SITE_DIR/_libcamera.so"
    printf 'from ._libcamera import *\n' > "$SITE_DIR/__init__.py"
    popd > /dev/null
    rm -rf "$BUILD_DIR"
    # Remove build tools
    apt-get remove -y -qq meson ninja-build pybind11-dev python3-ply libcamera-dev
    apt-get autoremove -y -qq
else
    echo "[3/11] Python 3.12 libcamera bindings already installed — skipping."
fi

# ── 4. Python venv ───────────────────────────────────────────────────────────
echo "[4/11] Creating Python venv..."
if [ ! -d "$VENV" ]; then
    sudo -u "$REAL_USER" python3 -m venv "$VENV" --system-site-packages
fi
# Ensure libcamera system path is on venv's path
PTH="$VENV/lib/python3.12/site-packages/libcamera-path.pth"
if [ ! -f "$PTH" ]; then
    echo "/usr/lib/aarch64-linux-gnu/python3.12/site-packages" > "$PTH"
    chown "$REAL_USER:$REAL_USER" "$PTH"
fi

# ── 5. Pip requirements ──────────────────────────────────────────────────────
echo "[5/11] Installing pip requirements..."
sudo -u "$REAL_USER" "$VENV/bin/pip" install -q -r "$SCRIPT_DIR/requirements.txt"
sudo -u "$REAL_USER" "$VENV/bin/pip" install -q picamera2

# ── 6. Patch picamera2 DrmPreview (headless fix) ────────────────────────────
echo "[6/11] Patching picamera2 for headless operation..."
PREV_INIT=$("$VENV/bin/python3" -c \
    "import importlib.util, os; s=importlib.util.find_spec('picamera2'); print(os.path.dirname(s.origin)) if s else print('')" \
    2>/dev/null)/previews/__init__.py
if [ -f "$PREV_INIT" ] && ! grep -q "DrmPreview unavailable" "$PREV_INIT"; then
    python3 - "$PREV_INIT" << 'PYEOF'
import sys, re, pathlib
p = pathlib.Path(sys.argv[1])
txt = p.read_text()
old = "from .drm_preview import DrmPreview"
new = """try:
    from .drm_preview import DrmPreview
except (ImportError, ModuleNotFoundError):
    class DrmPreview:
        def __init__(self, *a, **kw):
            raise RuntimeError("DrmPreview unavailable: pykms not installed")"""
if old in txt:
    p.write_text(txt.replace(old, new))
    print("  Patched:", sys.argv[1])
else:
    print("  Already patched or not found — skipping")
PYEOF
fi

# ── 7. /boot/firmware/config.txt ────────────────────────────────────────────
echo "[7/11] Configuring /boot/firmware/config.txt..."
CONFIG=/boot/firmware/config.txt
# Replace camera_auto_detect=1 with 0, or add if missing
if grep -q "camera_auto_detect=1" "$CONFIG"; then
    sed -i 's/camera_auto_detect=1/camera_auto_detect=0/' "$CONFIG"
elif ! grep -q "camera_auto_detect" "$CONFIG"; then
    echo "camera_auto_detect=0" >> "$CONFIG"
fi
# Add imx219 overlay if not present
if ! grep -q "dtoverlay=imx219" "$CONFIG"; then
    echo "dtoverlay=imx219,cam0" >> "$CONFIG"
fi
# Ensure UART is enabled
if ! grep -q "enable_uart=1" "$CONFIG"; then
    echo "enable_uart=1" >> "$CONFIG"
fi

# ── 8. /boot/firmware/cmdline.txt — remove serial console ───────────────────
echo "[8/11] Removing serial console from cmdline.txt..."
CMDLINE=/boot/firmware/cmdline.txt
if grep -q "console=serial0" "$CMDLINE"; then
    sed -i 's/console=serial0,[0-9]* //' "$CMDLINE"
    echo "  Removed console=serial0 from cmdline.txt"
else
    echo "  Already clean."
fi

# ── 9. dialout group + UART alias ───────────────────────────────────────────
echo "[9/11] Adding $REAL_USER to dialout group..."
usermod -a -G dialout "$REAL_USER"
# Create /dev/ttyRobot pointing to the GPIO header UART regardless of Pi model.
# RPi 5: GPIO UART = ttyAMA10 (ttyAMA0 is an internal RP1 UART — wrong device)
# RPi 4: GPIO UART = ttyAMA0 (ttyAMA10 does not exist)
if [ -e /dev/ttyAMA10 ]; then
    echo 'KERNEL=="ttyAMA10", SYMLINK+="ttyRobot"' \
        > /etc/udev/rules.d/99-uart-v2x.rules
    echo "  ttyRobot → ttyAMA10 (RPi 5)"
elif [ -e /dev/ttyAMA0 ]; then
    echo 'KERNEL=="ttyAMA0", SYMLINK+="ttyRobot"' \
        > /etc/udev/rules.d/99-uart-v2x.rules
    echo "  ttyRobot → ttyAMA0 (RPi 4)"
fi
udevadm control --reload-rules
udevadm trigger
echo "  /dev/ttyRobot ready"

# ── 10. Build OBU binary + generate obu_local.json ──────────────────────────
echo "[10/11] Building OBU binary..."
OBU_DIR="$REPO_DIR/v2x_testbed/obu"
OBU_BIN="$OBU_DIR/build/obu_client"
if [ ! -f "$OBU_BIN" ]; then
    mkdir -p "$OBU_DIR/build"
    pushd "$OBU_DIR/build" > /dev/null
    cmake .. -DCMAKE_BUILD_TYPE=Release -DCMAKE_MAKE_PROGRAM=make > /dev/null 2>&1
    make -j$(nproc) obu_client 2>&1 | tail -3
    popd > /dev/null
    echo "  Built: $OBU_BIN"
else
    echo "  Already built — skipping."
fi

# Generate obu_local.json — unique entity_id per device from hostname
MY_HOSTNAME=$(hostname)
# Sanitise: uppercase, hyphens → underscores, strip non-alphanumeric
ENTITY_ID=$(echo "$MY_HOSTNAME" | tr '[:lower:]-' '[:upper:]_' | tr -cd 'A-Z0-9_')
IS_EMERGENCY="false"
if [ "$ROLE" = "ambulance" ]; then IS_EMERGENCY="true"; fi
RSU_IP=$(python3 -c "import json; c=json.load(open('$OBU_DIR/config/obu1_config.json')); print(c['rsu_ip'])" 2>/dev/null || echo "192.168.0.103")
DESKTOP_IP=$(python3 -c "import json; c=json.load(open('$OBU_DIR/config/obu1_config.json')); print(c['desktop_ip'])" 2>/dev/null || echo "192.168.0.103")
# Ambulance re-authenticates every ~2s from the same port, which causes RSU session
# lookup collisions. Port 0 lets the OS assign a fresh ephemeral port each restart,
# so every new auth cycle has a unique ip:port key in the RSU session table.
UDP_LISTEN_PORT=5003
if [ "$ROLE" = "ambulance" ]; then UDP_LISTEN_PORT=0; fi
POST_AUTH_COUNT=1
if [ "$ROLE" = "ambulance" ]; then POST_AUTH_COUNT=60; fi
cat > "$OBU_DIR/config/obu_local.json" << OBUEOF
{
    "entity_id": "${ENTITY_ID}",
    "obu_ip": "0.0.0.0",
    "udp_listen_port": ${UDP_LISTEN_PORT},
    "rsu_ip": "${RSU_IP}",
    "rsu_port": 5000,
    "desktop_ip": "${DESKTOP_IP}",
    "desktop_reg_port": 8001,
    "is_emergency": ${IS_EMERGENCY},
    "delta_ts_ms": 500,
    "post_auth_count": ${POST_AUTH_COUNT},
    "crypto_provider": "placeholder",
    "key_directory": "./keys_${MY_HOSTNAME}/"
}
OBUEOF
chown "$REAL_USER:$REAL_USER" "$OBU_DIR/config/obu_local.json"
echo "  Generated obu_local.json  entity_id=${ENTITY_ID}  is_emergency=${IS_EMERGENCY}"

# ── 11. CLI commands ─────────────────────────────────────────────────────────
echo "[11/12] Installing CLI commands..."
chmod +x "$SCRIPT_DIR/v2x_run_car.sh" "$SCRIPT_DIR/v2x_run_ambulance.sh" "$SCRIPT_DIR/v2x_robot_log.sh"
ln -sf "$SCRIPT_DIR/v2x_run_car.sh"       /usr/local/bin/v2x_run_car
ln -sf "$SCRIPT_DIR/v2x_run_ambulance.sh" /usr/local/bin/v2x_run_ambulance
ln -sf "$SCRIPT_DIR/v2x_robot_log.sh"     /usr/local/bin/v2x_robot_log
echo "  v2x_run_car / v2x_run_ambulance / v2x_robot_log → /usr/local/bin/"

# ── 12. Systemd service ──────────────────────────────────────────────────────
echo "[12/12] Installing systemd service (v2x_$ROLE)..."
SERVICE_SRC="$SCRIPT_DIR/v2x_${ROLE}.service"
SERVICE_DST="/etc/systemd/system/v2x_${ROLE}.service"
if [ ! -f "$SERVICE_SRC" ]; then
    echo "  ERROR: $SERVICE_SRC not found"
    exit 1
fi
cp "$SERVICE_SRC" "$SERVICE_DST"
systemctl daemon-reload
systemctl enable "v2x_${ROLE}"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Setup complete!                                              ║"
echo "║                                                              ║"
echo "║  Before rebooting, edit these files:                         ║"
echo "║                                                              ║"
echo "║  v2x_testbed/obu/config/obu1_config.json                     ║"
echo "║    → set rsu_ip and desktop_ip to your laptop WiFi IP        ║"
echo "║    (both car and ambulance read from this same file)          ║"
echo "║                                                              ║"
echo "║  Then:  sudo reboot                                          ║"
echo "║  Check: sudo journalctl -fu v2x_$ROLE                        ║"
echo "╚══════════════════════════════════════════════════════════════╝"
