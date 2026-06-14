#!/usr/bin/env python3
"""
v2x_obu_trigger.py — joystick Mode button → toggle V2X OBU service.

Reads /dev/input/js0 using the raw Linux joystick API (no pygame, no conflict
with main_car.py or main_ambulance.py). On Mode button press: if the v2x service
is active → stop it (OFFLINE); if stopped → regenerate config, clear keys,
restart it (ONLINE).

Installed as v2x_obu_trigger.service by setup.sh.

Usage: python3 v2x_obu_trigger.py [car|ambulance] [mode_button_index]

Mode button index: check your controller with  jstest /dev/input/js0
  Common values: 8 = Mode on many RF gamepads, 6 = Select/Back on Xbox-style
"""

import json
import logging
import os
import shutil
import struct
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [OBU-TRIGGER] %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

ROLE        = sys.argv[1] if len(sys.argv) > 1 else 'car'
MODE_BUTTON = int(sys.argv[2]) if len(sys.argv) > 2 else 8   # adjust via setup.sh
JS_DEVICE   = '/dev/input/js0'
SERVICE     = f'v2x_{ROLE}'

SCRIPT_DIR     = Path(__file__).resolve().parent
REPO_DIR       = SCRIPT_DIR.parent
OBU_DIR        = REPO_DIR / 'v2x_testbed' / 'obu'
OBU_CONFIG_REF = OBU_DIR / 'config' / 'obu1_config.json'
OBU_LOCAL      = OBU_DIR / 'config' / 'obu_local.json'

MY_HOSTNAME = subprocess.check_output(['hostname'], text=True).strip()
ENTITY_ID   = ''.join(
    c for c in MY_HOSTNAME.upper().replace('-', '_') if c.isalnum() or c == '_'
)
KEY_DIR = SCRIPT_DIR / f'keys_{MY_HOSTNAME}'

# Read IPs from reference config
try:
    ref        = json.loads(OBU_CONFIG_REF.read_text())
    RSU_IP     = ref.get('rsu_ip', '127.0.0.1')
    DESKTOP_IP = ref.get('desktop_ip', '127.0.0.1')
except Exception:
    RSU_IP     = '127.0.0.1'
    DESKTOP_IP = '127.0.0.1'

# ── Raw joystick API ──────────────────────────────────────────────────────────
# struct js_event { u32 time; s16 value; u8 type; u8 number; }
_JS_STRUCT      = struct.Struct('IhBB')
_JS_BTN_TYPE    = 0x01
_JS_INIT_MASK   = 0x80  # synthetic init events on open — ignore these

# ── Helpers ───────────────────────────────────────────────────────────────────

def _notify_desktop(status: str):
    try:
        payload = json.dumps({'entity_id': ENTITY_ID, 'status': status}).encode()
        req = urllib.request.Request(
            f'http://{DESKTOP_IP}:5000/api/entity_status',
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        urllib.request.urlopen(req, timeout=3)
        log.info("Desktop notified: %s %s", ENTITY_ID, status)
    except Exception as e:
        log.warning("Desktop notification failed (%s) — will retry via heartbeat", e)


def _is_service_active() -> bool:
    r = subprocess.run(['systemctl', 'is-active', SERVICE],
                       capture_output=True, text=True)
    return r.stdout.strip() == 'active'


def _regen_obu_local():
    is_emgy     = (ROLE == 'ambulance')
    listen_port = 0 if is_emgy else 5003
    post_count  = 60 if is_emgy else 1
    cfg = {
        'entity_id':        ENTITY_ID,
        'obu_ip':           '0.0.0.0',
        'udp_listen_port':  listen_port,
        'rsu_ip':           RSU_IP,
        'rsu_port':         5000,
        'desktop_ip':       DESKTOP_IP,
        'desktop_reg_port': 8001,
        'is_emergency':     is_emgy,
        'delta_ts_ms':      500,
        'post_auth_count':  post_count,
        'crypto_provider':  'placeholder',
        'key_directory':    f'./keys_{MY_HOSTNAME}/',
    }
    OBU_LOCAL.write_text(json.dumps(cfg, indent=4))
    log.info("Regenerated obu_local.json  entity=%s  emergency=%s", ENTITY_ID, is_emgy)


def _start_service():
    log.info("Starting %s...", SERVICE)
    _regen_obu_local()
    if KEY_DIR.exists():
        shutil.rmtree(KEY_DIR)
        log.info("Cleared key dir: %s", KEY_DIR)
    subprocess.run(['systemctl', 'restart', SERVICE], check=False)
    log.info("Service %s started", SERVICE)
    _notify_desktop('ONLINE')


def _stop_service():
    log.info("Stopping %s...", SERVICE)
    subprocess.run(['systemctl', 'stop', SERVICE], check=False)
    log.info("Service %s stopped", SERVICE)
    _notify_desktop('OFFLINE')


def _toggle():
    if _is_service_active():
        _stop_service()
    else:
        _start_service()

# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    log.info("V2X OBU trigger  role=%s  service=%s  Mode=btn%d  device=%s",
             ROLE, SERVICE, MODE_BUTTON, JS_DEVICE)
    log.info("entity_id=%s  desktop=%s  rsu=%s", ENTITY_ID, DESKTOP_IP, RSU_IP)

    while True:
        try:
            with open(JS_DEVICE, 'rb') as js:
                log.info("Joystick connected: %s", JS_DEVICE)
                while True:
                    raw = js.read(_JS_STRUCT.size)
                    if len(raw) < _JS_STRUCT.size:
                        break
                    ts, value, type_, number = _JS_STRUCT.unpack(raw)
                    # Ignore synthetic init events (type has 0x80 bit set)
                    if type_ & _JS_INIT_MASK:
                        continue
                    if type_ == _JS_BTN_TYPE and number == MODE_BUTTON and value == 1:
                        log.info("Mode button pressed — toggling OBU")
                        _toggle()
        except FileNotFoundError:
            log.warning("No joystick at %s — retrying in 5s", JS_DEVICE)
            time.sleep(5)
        except Exception as e:
            log.error("Joystick error: %s — retrying in 5s", e)
            time.sleep(5)


if __name__ == '__main__':
    main()
