#!/usr/bin/env python3
"""
V2X Ambulance Robot — pure Python main loop.

No emergency handler — the ambulance drives through while broadcasting V2X.

Usage:
  python3 main_ambulance.py
  python3 main_ambulance.py --car-ip 192.168.1.x
  python3 main_ambulance.py --debug-image
  python3 main_ambulance.py --obu-binary ../v2x_testbed/obu/build/obu_client \\
                            --obu-config  ../v2x_testbed/obu/config/obu_local.json

Joystick:
  Hold LB (deadman)  → manual drive
  Start              → arm / disarm
  A button           → simulate V2X emergency ON  (test without OBU)
  B button           → simulate V2X emergency OFF

Trigger emergency broadcast (manual, from another terminal):
  python3 control_socket.py --port 5011 emergency_on
  python3 control_socket.py --port 5011 emergency_off
"""

import argparse
import csv
import logging
import os
import signal
import socket
import sys
import threading
import time

import yaml

from algorithms           import create_follower
from camera               import Camera
from control_socket       import ControlSocket
from joystick             import Joystick
from position             import PositionEstimator
from position_broadcaster import PositionBroadcaster
from robot_driver         import RobotDriver
from stream_server        import StreamServer
from v2x_bridge           import V2XBridge

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('ambulance')

_LOG_PATH = os.path.expanduser('~/v2x_amb_run.csv')
_LOG_HZ   = 10
_LOG_COLS = [
    'time_s', 'vx', 'wz', 'zone', 'mode',
    'white_err_px', 'ly_px', 'n_strips',
    'tags_seen', 'emergency',
]


class RunLogger:
    def __init__(self, enabled: bool = True):
        self._enabled = enabled
        self._file    = None
        self._writer  = None
        self._t_start = 0.0
        self._t_last  = 0.0
        self._armed   = False

    def arm(self):
        if not self._enabled:
            return
        self._close()
        self._file   = open(_LOG_PATH, 'w', newline='', buffering=1)
        self._writer = csv.writer(self._file)
        self._writer.writerow(_LOG_COLS)
        self._t_start = time.monotonic()
        self._t_last  = 0.0
        self._armed   = True
        logger.info("Run log started → %s", _LOG_PATH)

    def disarm(self):
        self._armed = False
        if not self._enabled:
            return
        self._close()
        logger.info("Run log closed → %s", _LOG_PATH)

    def log(self, vx: float, wz: float, zone: int,
            follower, estimator, emergency: bool = False):
        if not self._armed or self._writer is None:
            return
        now = time.monotonic()
        if now - self._t_last < 1.0 / _LOG_HZ:
            return
        self._t_last = now

        info = follower.get_debug_info()
        _, tag_ids = estimator.get_last_detections()
        tags_str   = ';'.join(str(i) for i in tag_ids) if tag_ids else ''

        self._writer.writerow([
            round(now - self._t_start, 2),
            round(vx, 3),
            round(wz, 3),
            zone,
            info['mode'],
            info['white_err']    if info['white_err']    is not None else '',
            info.get('ly_px')    if info.get('ly_px')    is not None else '',
            info.get('n_strips') if info.get('n_strips') is not None else '',
            tags_str,
            1 if emergency else 0,
        ])

    def _close(self):
        if self._file:
            try:
                self._file.close()
            except Exception:
                pass
            self._file   = None
            self._writer = None


def _deep_merge(base: dict, override: dict):
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v

def load_config(path: str, role: str = '') -> dict:
    with open(path) as f:
        cfg = yaml.safe_load(f)
    if role and role in cfg:
        _deep_merge(cfg, cfg[role])
    for r in ('car', 'ambulance'):
        cfg.pop(r, None)
    return cfg


def _pi_temp() -> str:
    """Read Pi CPU temperature from sysfs. Returns e.g. '52.3C' or '---'."""
    try:
        raw = open('/sys/class/thermal/thermal_zone0/temp').read().strip()
        return f"{int(raw) / 1000:.1f}C"
    except Exception:
        return '---'


def _push_stream_amb(streamer, full_frame, roi_panels, crop_y,
                     estimator, bridge, joystick, armed, vx, wz, driver=None, name=''):
    import cv2, numpy as np
    from datetime import datetime
    top = cv2.resize(full_frame, (640, full_frame.shape[0]))
    cv2.line(top, (0, crop_y), (640, crop_y), (0, 215, 255), 1)
    cv2.putText(top, "crop", (4, max(crop_y - 3, 8)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 215, 255), 1)

    # Robot name — top-left, black outline for visibility over any background
    if name:
        cv2.putText(top, name, (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3)
        cv2.putText(top, name, (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)

    # Timestamp top-right corner
    ts = datetime.now().strftime('%H:%M:%S')
    cv2.putText(top, ts, (570, 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)

    corners, ids = estimator.get_last_detections()
    for pts, tag_id in zip(corners, ids):
        scaled = (pts[0] * [2, 1]).astype(np.int32)
        color  = (0, 255, 0) if tag_id < estimator._n_inner else (0, 165, 255)
        cv2.polylines(top, [scaled], True, color, 2)
        cx, cy = scaled.mean(axis=0).astype(int)
        cv2.putText(top, str(tag_id), (cx - 6, cy + 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

    if roi_panels is not None:
        mid = roi_panels
    else:
        mid = np.zeros((full_frame.shape[0] - crop_y, 640, 3), np.uint8)

    pos     = estimator.get_position()
    zone    = pos['zone'] if pos else -1
    off     = pos.get('off_track', False) if pos else False
    emg     = bridge.is_emergency()
    mode    = 'MANUAL' if joystick.is_manual() else 'AUTO'
    arm_lbl = 'ARMED' if armed else 'DISARMED'

    bar1 = np.zeros((22, 640, 3), np.uint8)
    col1 = (0, 50, 220) if emg else (0, 200, 200)
    row1 = [f"AMB zone={zone}", f"vx={vx:.2f}", f"wz={wz:+.2f}", "AMBULANCE"]
    if off:
        row1.append("OFF-TRACK")
    cv2.putText(bar1, "  ".join(row1), (4, 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, col1, 1)

    bar2 = np.zeros((22, 640, 3), np.uint8)
    arm_col = (0, 220, 50) if armed else (0, 80, 220)
    cv2.putText(bar2, arm_lbl, (4, 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, arm_col, 1)
    cv2.putText(bar2, mode, (110, 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 215, 255), 1)
    emg_txt = "V2X:BROADCASTING EMERGENCY" if emg else "V2X:STANDBY"
    emg_col = (0, 50, 220) if emg else (120, 120, 120)
    cv2.putText(bar2, emg_txt, (200, 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, emg_col, 1)

    # Battery from STM32 telemetry
    telem = driver.get_telemetry() if driver else None
    batt_txt = f"BAT:{telem['battery_v']:.1f}V" if telem else "BAT:---"
    cv2.putText(bar2, batt_txt, (430, 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (80, 200, 255), 1)

    # Pi CPU temperature
    temp_txt = f"PI:{_pi_temp()}"
    cv2.putText(bar2, temp_txt, (530, 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (80, 200, 255), 1)

    streamer.push_frame(np.vstack([top, mid, bar1, bar2]))


def main():
    ap = argparse.ArgumentParser(description='V2X Ambulance Robot')
    ap.add_argument('--config',         default='config.yaml')
    ap.add_argument('--car-ip',         default='',
                    help='IP of car robot (overrides config)')
    ap.add_argument('--obu-binary',     default='')
    ap.add_argument('--obu-config',     default='')
    ap.add_argument('--debug-image',    action='store_true')
    ap.add_argument('--debug-position', action='store_true')
    ap.add_argument('--serial-port',    default='')
    args = ap.parse_args()

    cfg = load_config(args.config, 'ambulance')

    # ── Robot driver ──────────────────────────────────────────────────────────
    rc = cfg['robot']
    sc = cfg['serial']
    driver = RobotDriver(
        port=args.serial_port or sc['port'],
        baudrate=sc['baudrate'],
        wheel_radius=rc['wheel_radius_m'],
        track_width=rc['track_width_m'],
        max_wheel_speed=rc['max_wheel_speed_rad_s'],
        cmd_timeout=rc['cmd_vel_timeout_s'],
        allow_wheel_reversal=rc.get('allow_wheel_reversal', False),
    )
    driver.start()
    time.sleep(1.0)

    # ── Camera ────────────────────────────────────────────────────────────────
    cc = cfg['camera']
    cam = Camera(
        device=cc['device'],
        width=cc['width'],
        height=cc['height'],
        use_picamera2=cc.get('use_picamera2', True),
    )
    cam_ok = cam.start()
    if not cam_ok:
        logger.warning("Camera not available — lane following disabled, V2X running")

    # ── Joystick ──────────────────────────────────────────────────────────────
    jc = cfg.get('joystick', {})
    joystick = Joystick(
        device_index=jc.get('device_index', 0),
        deadman_button=jc.get('deadman_button', 4),
        turbo_button=jc.get('turbo_button', 5),
        arm_button=jc.get('arm_button', 7),
        amb_arrive_button=jc.get('amb_arrive_button', 0),
        amb_depart_button=jc.get('amb_depart_button', 1),
        train_button=jc.get('train_button', 2),
        axis_throttle=jc.get('axis_throttle', 1),
        axis_steering=jc.get('axis_steering', 3),
        max_speed=jc.get('max_speed', 0.4),
        turbo_speed=jc.get('turbo_speed', 0.8),
        max_steering=jc.get('max_steering', 1.5),
        deadzone=jc.get('deadzone', 0.10),
        accel_rate=jc.get('accel_rate', 2.0),
        decel_rate=jc.get('decel_rate', 4.0),
    )
    joystick.start()

    # ── Lane follower ─────────────────────────────────────────────────────────
    lc = cfg['lane_follower']
    follower = create_follower(lc, debug=args.debug_image or lc.get('debug_image', False))
    logger.info("Lane follower algorithm: %s", lc.get('algorithm', 'pure_pursuit'))

    # ── Position estimator + broadcaster ─────────────────────────────────────
    pc = cfg['position']
    estimator = PositionEstimator(
        n_inner_tags=pc['n_inner_tags'],
        n_outer_tags=pc['n_outer_tags'],
        tag_spacing_m=pc['tag_spacing_m'],
        tag_size_m=pc['tag_size_m'],
        focal_px=pc['focal_px'],
        detect_every_n=pc['detect_every_n'],
        debug=args.debug_position or pc.get('debug_image', False),
    )

    pbc    = cfg['position_broadcaster']
    car_ip = args.car_ip or pbc.get('peer_ip', '')
    broadcaster = PositionBroadcaster(
        peer_ip=car_ip,
        peer_port=pbc['peer_port'],
        broadcast_hz=pbc['broadcast_hz'],
        role='ambulance',
    )
    broadcaster.start()

    # ── V2X bridge ────────────────────────────────────────────────────────────
    vc = cfg['v2x_bridge']
    bridge = V2XBridge(
        role='ambulance',
        obu_binary=args.obu_binary or vc.get('obu_binary', ''),
        obu_config=args.obu_config  or vc.get('obu_config', ''),
        manual_mode=vc['manual_mode'],
        car_alert_port=vc['car_alert_port'],
        exit_clear_delay_s=vc['exit_clear_delay_s'],
        obu_loop_count=vc.get('obu_loop_count', 1),
    )
    bridge.start()

    # ── Vision stream (desktop browser) ──────────────────────────────────────
    stc = cfg.get('stream', {})
    streamer = None
    _robot_name = ''.join(
        c for c in socket.gethostname().upper().replace('-', '_')
        if c.isalnum() or c == '_'
    )
    if stc.get('enabled', False):
        streamer = StreamServer(port=stc.get('port', 5005), name=_robot_name)
        streamer.start()

    # ── Control socket ────────────────────────────────────────────────────────
    ctrl = ControlSocket(port=cfg['control']['port'])
    ctrl.register('emergency_on',  lambda: bridge.set_emergency(True))
    ctrl.register('emergency_off', lambda: bridge.set_emergency(False))
    ctrl.register('arm',           driver.arm)
    ctrl.register('disarm',        driver.disarm)
    ctrl.register('estop',         driver.estop)
    ctrl.register('status',        lambda: logger.info(bridge.status()))
    ctrl.start()

    logger.info("")
    logger.info("╔══════════════════════════════════════════════════════╗")
    logger.info("║         V2X AMBULANCE ROBOT READY                    ║")
    logger.info("║  Lane following  : ACTIVE  (%.2f m/s)                 ║",
                lc['linear_speed'])
    logger.info("║  Joystick        : %s",
                "CONNECTED (hold btn%d to drive)" % jc.get('deadman_button', 4)
                if joystick.connected() else "not found — autonomous only          ║")
    logger.info("║  V2X broadcast   : STANDBY (A=ON  B=OFF)             ║")
    logger.info("╚══════════════════════════════════════════════════════╝")
    logger.info("")

    def _sigterm(*_):
        threading.Timer(5.0, lambda: os.kill(os.getpid(), signal.SIGKILL)).start()
        sys.exit(0)
    signal.signal(signal.SIGTERM, _sigterm)

    _robot_armed   = False
    _stream_vx     = 0.0
    _stream_wz     = 0.0
    _last_stream_t = 0.0
    _crop_y        = int(lc['crop_top_ratio'] * cc['height'])
    _run_log       = RunLogger(enabled=cfg.get('logging', {}).get('run_log', True))
    own_pos        = None

    try:
        while True:
            # ── Joystick buttons ──────────────────────────────────────────────
            # A button: start emergency broadcast (for testing without OBU)
            if joystick.get_amb_arrive():
                bridge.set_emergency(True)
                logger.info("*** SIM: emergency BROADCAST ON (A button) ***")
            # B button: stop emergency broadcast
            if joystick.get_amb_depart():
                bridge.set_emergency(False)
                logger.info("*** SIM: emergency BROADCAST OFF (B button) ***")
            # X button: toggle training recording (recorded_path algorithm)
            if joystick.get_train_toggle() and hasattr(follower, 'toggle_training'):
                follower.toggle_training()
            # Start button: arm / disarm
            if joystick.get_arm_press():
                _robot_armed = not _robot_armed
                if _robot_armed:
                    driver.arm()
                    _run_log.arm()
                    logger.info("*** ARMED (Start button) ***")
                else:
                    driver.set_velocity(0.0, 0.0)
                    driver.disarm()
                    _run_log.disarm()
                    logger.info("*** DISARMED (Start button) ***")

            # ── Camera grab + stream (always, regardless of arm state) ────────
            # Keeps picamera2 buffer drained continuously — prevents flickering.
            frame = cam.get_frame()

            if streamer and frame is not None:
                now = time.monotonic()
                if now - _last_stream_t >= 0.04:
                    _last_stream_t = now
                    panels = follower.get_roi_panels()
                    _push_stream_amb(streamer, frame, panels, _crop_y,
                                     estimator, bridge, joystick,
                                     _robot_armed, _stream_vx, _stream_wz,
                                     driver=driver, name=_robot_name)

            if not _robot_armed:
                if frame is None:
                    time.sleep(0.02)
                continue

            # ── Position update (only when armed) ─────────────────────────────
            if frame is not None:
                estimator.process(frame)
                own_pos = estimator.get_position()
                broadcaster.set_own_position(own_pos)

            zone = own_pos['zone'] if own_pos else -1
            follower.set_zone(zone)

            # ── Velocity decision ─────────────────────────────────────────────
            js_cmd = joystick.get_command()
            if js_cmd is not None:
                vx, wz = js_cmd
                if hasattr(follower, 'record') and follower.is_recording():
                    follower.record(vx, wz, zone)
            elif frame is not None:
                vx, wz = follower.process(frame)
            else:
                vx, wz = 0.0, 0.0

            driver.set_velocity(vx, wz)
            _stream_vx, _stream_wz = vx, wz

            _run_log.log(vx, wz, zone, follower, estimator,
                         emergency=bridge.is_emergency())

            if frame is None:
                time.sleep(0.02)

    except KeyboardInterrupt:
        logger.info("Shutting down…")
    finally:
        _run_log.disarm()
        driver.set_velocity(0.0, 0.0)
        time.sleep(0.1)
        driver.disarm()
        driver.stop()
        bridge.stop()
        broadcaster.stop()
        joystick.stop()
        ctrl.stop()
        if streamer:
            streamer.stop()
        cam.stop()


if __name__ == '__main__':
    main()
