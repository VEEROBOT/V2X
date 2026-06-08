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
#  11. Installs and enables systemd service
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

# ── 1. System packages ──────────────────────────────────────────────────────
echo "[1/11] Installing system packages..."
apt-get update -qq
apt-get install -y -qq \
    python3-pip python3-picamera2 python3-pygame \
    libcap-dev joystick \
    cmake libssl-dev build-essential \
    git curl gpg

# ── 2. Raspberry Pi apt repo (for libcamera 0.5) ────────────────────────────
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
apt-get update -qq
apt-get install -y -qq libcamera0.5 libcamera-ipa libcamera-tools

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
    cd build && ninja src/py/libcamera/pylibcamera
    SITE_DIR=/usr/lib/aarch64-linux-gnu/python3.12/site-packages/libcamera
    mkdir -p "$SITE_DIR"
    cp src/py/libcamera/_libcamera*.so "$SITE_DIR/_libcamera.so"
    # Copy __init__.py from Ubuntu's python3-libcamera package
    dpkg -L python3-libcamera 2>/dev/null | grep __init__ | xargs -I{} cp {} "$SITE_DIR/" 2>/dev/null || true
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

# ── 6. Patch picamera2 DrmPreview (headless fix) ────────────────────────────
echo "[6/11] Patching picamera2 for headless operation..."
PREV_INIT=$("$VENV/bin/python3" -c \
    "import picamera2, os; print(os.path.dirname(picamera2.__file__))" \
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

# ── 9. dialout group ────────────────────────────────────────────────────────
echo "[9/11] Adding $REAL_USER to dialout group..."
usermod -a -G dialout "$REAL_USER"

# ── 10. Build OBU binary ─────────────────────────────────────────────────────
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

# ── 11. Systemd service ──────────────────────────────────────────────────────
echo "[11/11] Installing systemd service (v2x_$ROLE)..."
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
if [ "$ROLE" = "car" ]; then
echo "║  v2x_testbed/obu/config/obu1_config.json                     ║"
echo "║    → set rsu_ip to your laptop/RSU WiFi IP                   ║"
else
echo "║  v2x_testbed/obu/config/obu2_config.json                     ║"
echo "║    → set rsu_ip to your laptop/RSU WiFi IP                   ║"
fi
echo "║                                                              ║"
echo "║  Then:  sudo reboot                                          ║"
echo "║  Check: sudo journalctl -fu v2x_$ROLE                        ║"
echo "╚══════════════════════════════════════════════════════════════╝"
