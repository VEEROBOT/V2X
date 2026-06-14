#!/usr/bin/env python3
"""
V2X Car Robot — pure Python main loop.

Node graph (replaces entire ROS2 launch):
  Camera → lane_follower → emergency_handler → robot_driver → STM32
  Camera → position_estimator → position_broadcaster ↔ UDP ↔ ambulance
  v2x_bridge ← RSU UDP alert (or manual control socket)
  joystick → overrides lane_follower when deadman held

Usage:
  python3 main_car.py
  python3 main_car.py --ambulance-ip 192.168.1.x
  python3 main_car.py --debug-image --debug-position
  python3 main_car.py --obu-binary /home/pi/v2x/obu/build/obu_client \\
                      --obu-config  /home/pi/v2x/obu/config/obu1_config.json \\
                      --ambulance-ip 192.168.1.x

Manual emergency (from another terminal on same Pi):
  python3 control_socket.py --port 5010 emergency_on
  python3 control_socket.py --port 5010 emergency_off
"""

import argparse
import csv
import logging
import math
import os
import signal
import socket
import sys
import threading
import time

import yaml

from camera               import Camera
from joystick             import Joystick
from robot_driver         import RobotDriver
from algorithms           import create_follower
from position             import PositionEstimator
from position_broadcaster import PositionBroadcaster
from v2x_bridge           import V2XBridge
from emergency_handler    import EmergencyHandler
from control_socket       import ControlSocket
from stream_server        import StreamServer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('car')

_LOG_PATH = os.path.expanduser('~/v2x_run.csv')
_LOG_HZ   = 10          # rows per second written to the log
_LOG_COLS = [
    'time_s', 'vx', 'wz', 'zone', 'mode',
    'white_err_px',  # Lx for pure_pursuit, centroid error for centroid
    'ly_px',         # lookahead y-distance (pure_pursuit only; blank for centroid)
    'n_strips',      # number of white strips detected (pure_pursuit only)
    'wz_enc',        # actual angular rate from encoder RPMs (rad/s)
    'gyro_z',        # IMU yaw rate (rad/s) — independent of commanded wz
    'tags_seen',
    'eh_state',      # emergency handler FSM state (NORMAL/EVADING/HOLDING/RECOVERING/RESUMING)
    'emergency',     # 1 when V2X or sim emergency flag is active
]


class RunLogger:
    """
    Writes a CSV run log while the robot is armed.

    File: ~/v2x_run.csv — overwritten at the start of each arm session.
    Cleared on every arm press so old data never accumulates.
    Delete manually with:  rm ~/v2x_run.csv

    Disable entirely with  logging.run_log: false  in config.yaml.
    """

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
            follower, estimator, driver=None, handler=None, emergency: bool = False):
        if not self._armed or self._writer is None:
            return
        now = time.monotonic()
        if now - self._t_last < 1.0 / _LOG_HZ:
            return
        self._t_last = now

        info = follower.get_debug_info()
        _, tag_ids = estimator.get_last_detections()
        tags_str   = ';'.join(str(i) for i in tag_ids) if tag_ids else ''

        wz_enc  = ''
        gyro_z  = ''
        if driver is not None:
            telem = driver.get_telemetry()
            if telem:
                rpm  = telem['wheel_rpm']      # [FL, BL, BR, FR]
                r    = 0.065                   # wheel_radius_m
                k    = (2.0 * math.pi / 60.0) * r   # rpm → linear m/s
                v_l  = (rpm[0] + rpm[1]) / 2.0 * k
                v_r  = (rpm[2] + rpm[3]) / 2.0 * k
                wz_enc = round((v_r - v_l) / 0.377, 3)   # track_width_m
                gyro_z = round(telem['gyro_z'], 3)

        self._writer.writerow([
            round(now - self._t_start, 2),
            round(vx, 3),
            round(wz, 3),
            zone,
            info['mode'],
            info['white_err']  if info['white_err'] is not None else '',
            info.get('ly_px')  if info.get('ly_px')  is not None else '',
            info.get('n_strips') if info.get('n_strips') is not None else '',
            wz_enc,
            gyro_z,
            tags_str,
            handler.get_state() if handler is not None else '',
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
    """Read Pi CPU temperature from sysfs. Returns e.g. '52.3°C' or '---'."""
    try:
        raw = open('/sys/class/thermal/thermal_zone0/temp').read().strip()
        return f"{int(raw) / 1000:.1f}C"
    except Exception:
        return '---'


def _push_stream(streamer, full_frame, roi_panels, crop_y,
                 estimator, handler, bridge, broadcaster,
                 joystick, armed, vx, wz, driver=None, name=''):
    import cv2, numpy as np
    from datetime import datetime
    # Top row: full camera frame (scaled 2× wider) with crop boundary
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

    # AprilTag overlay (x-coords ×2 because top panel is 2× wider than source)
    corners, ids = estimator.get_last_detections()
    for pts, tag_id in zip(corners, ids):
        scaled = (pts[0] * [2, 1]).astype(np.int32)
        color  = (0, 255, 0) if tag_id < estimator._n_inner else (0, 165, 255)
        cv2.polylines(top, [scaled], True, color, 2)
        cx, cy = scaled.mean(axis=0).astype(int)
        cv2.putText(top, str(tag_id), (cx - 6, cy + 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

    # Middle row: lane overlay + HSV mask panels from LaneFollower
    if roi_panels is not None:
        mid = roi_panels
    else:
        mid = np.zeros((full_frame.shape[0] - crop_y, 640, 3), np.uint8)

    # ── Status bar — row 1: position + speed + state ──────────────────────
    pos       = estimator.get_position()
    zone      = pos['zone'] if pos else -1
    off       = pos.get('off_track', False) if pos else False
    peer_pos  = broadcaster.get_peer_position()
    peer_zone = peer_pos['zone'] if peer_pos else -1
    state     = handler.get_state()
    emg       = state != 'NORMAL'
    mode      = 'MANUAL' if joystick.is_manual() else 'AUTO'
    arm_lbl   = 'ARMED' if armed else 'DISARMED'

    bar1 = np.zeros((22, 640, 3), np.uint8)
    col1 = (0, 50, 220) if emg else (0, 200, 50)
    row1 = [f"CAR zone={zone}", f"AMB zone={peer_zone}",
            f"vx={vx:.2f}", f"wz={wz:+.2f}", state]
    if off: row1.append("OFF-TRACK")
    cv2.putText(bar1, "  ".join(row1), (4, 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, col1, 1)

    # ── Status bar — row 2: arm + mode + V2X + battery + Pi temp ─────────
    bar2 = np.zeros((22, 640, 3), np.uint8)
    arm_col = (0, 220, 50) if armed else (0, 80, 220)
    v2x_col = (0, 50, 220) if emg else (120, 120, 120)
    cv2.putText(bar2, arm_lbl, (4, 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, arm_col, 1)
    cv2.putText(bar2, mode, (110, 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 215, 255), 1)
    v2x_txt = "V2X:EMERGENCY" if emg else ("V2X:ACTIVE" if bridge.is_emergency() else "V2X:STANDBY")
    cv2.putText(bar2, v2x_txt, (200, 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, v2x_col, 1)

    # Battery from STM32 telemetry
    telem = driver.get_telemetry() if driver else None
    batt_txt = f"BAT:{telem['battery_v']:.1f}V" if telem else "BAT:---"
    cv2.putText(bar2, batt_txt, (370, 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (80, 200, 255), 1)

    # Pi CPU temperature
    temp_txt = f"PI:{_pi_temp()}"
    cv2.putText(bar2, temp_txt, (480, 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (80, 200, 255), 1)

    streamer.push_frame(np.vstack([top, mid, bar1, bar2]))


def main():
    ap = argparse.ArgumentParser(description='V2X Car Robot')
    ap.add_argument('--config',         default='config.yaml')
    ap.add_argument('--ambulance-ip',   default='',
                    help='IP of ambulance robot (overrides config)')
    ap.add_argument('--obu-binary',     default='')
    ap.add_argument('--obu-config',     default='')
    ap.add_argument('--debug-image',    action='store_true',
                    help='Show lane detection debug window')
    ap.add_argument('--debug-position', action='store_true',
                    help='Show AprilTag detection debug window')
    ap.add_argument('--serial-port',    default='',
                    help='Override serial port (e.g. /dev/ttyUSB0)')
    args = ap.parse_args()

    cfg = load_config(args.config, 'car')

    # ── Robot driver (STM32 via UART) ─────────────────────────────────────
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
    time.sleep(1.0)   # wait for STM32 ROS-mode init

    # ── Camera ────────────────────────────────────────────────────────────
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

    # ── Joystick ──────────────────────────────────────────────────────────
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
    joystick.start()   # non-fatal — returns False if no joystick, robot just runs autonomously

    # ── Lane follower ─────────────────────────────────────────────────────
    lc = cfg['lane_follower']
    follower = create_follower(lc, debug=args.debug_image or lc.get('debug_image', False))
    logger.info("Lane follower algorithm: %s", lc.get('algorithm', 'pure_pursuit'))

    # ── Position estimator + broadcaster ─────────────────────────────────
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

    pbc      = cfg['position_broadcaster']
    amb_ip   = args.ambulance_ip or pbc.get('peer_ip', '')
    broadcaster = PositionBroadcaster(
        peer_ip=amb_ip,
        peer_port=pbc['peer_port'],
        broadcast_hz=pbc['broadcast_hz'],
        role='car',
    )
    broadcaster.start()

    # ── V2X bridge ────────────────────────────────────────────────────────
    vc = cfg['v2x_bridge']
    bridge = V2XBridge(
        role='car',
        obu_binary=args.obu_binary or vc.get('obu_binary', ''),
        obu_config=args.obu_config  or vc.get('obu_config', ''),
        manual_mode=vc['manual_mode'],
        car_alert_port=vc['car_alert_port'],
        exit_clear_delay_s=vc['exit_clear_delay_s'],
        obu_loop_count=vc.get('obu_loop_count', 1),
    )
    bridge.start()

    # ── Emergency handler ─────────────────────────────────────────────────
    ec = cfg['emergency_handler']
    handler = EmergencyHandler(
        driving_direction      = ec.get('driving_direction',       'clockwise'),
        evasion_side           = ec.get('evasion_side',            'inner'),
        evasion_linear_speed   = ec.get('evasion_linear_speed',   0.06),
        evasion_angular_speed  = ec.get('evasion_angular_speed',  0.35),
        evasion_duration_s     = ec.get('evasion_duration_s',     6.0),
        min_evasion_s          = ec.get('min_evasion_s',          0.5),
        evasion_yellow_target  = ec.get('evasion_yellow_target',  0.70),
        evasion_yellow_kp      = ec.get('evasion_yellow_kp',      2.5),
        hold_linear_speed      = ec.get('hold_linear_speed',      0.04),
        recovery_linear_speed  = ec.get('recovery_linear_speed',  0.08),
        recovery_angular_speed = ec.get('recovery_angular_speed', 0.45),
        recovery_duration_s    = ec.get('recovery_duration_s',    2.5),
        hold_timeout_s         = ec.get('hold_timeout_s',         30.0),
        clear_delay_s          = ec.get('clear_delay_s',          1.0),
        resume_ramp_duration_s = ec.get('resume_ramp_duration_s', 2.0),
        n_tags                 = ec.get('n_tags',                 10),
        yield_zone_gap         = ec.get('yield_zone_gap',         3),
        position_timeout_s     = ec.get('position_timeout_s',     3.0),
    )

    # ── Vision stream (desktop browser) ──────────────────────────────────
    sc = cfg.get('stream', {})
    streamer = None
    _robot_name = ''.join(
        c for c in socket.gethostname().upper().replace('-', '_')
        if c.isalnum() or c == '_'
    )
    if sc.get('enabled', False):
        streamer = StreamServer(port=sc.get('port', 5005), name=_robot_name)
        streamer.start()

    # ── Control socket (manual test without OBU) ──────────────────────────
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
    logger.info("║         V2X CAR ROBOT READY                          ║")
    logger.info("║  Lane following  : ACTIVE                            ║")
    logger.info("║  Joystick        : %s",
                "CONNECTED (hold btn%d to drive)" % jc.get('deadman_button', 5)
                if joystick.connected() else "not found — autonomous only          ║")
    logger.info("║  V2X emergency   : MONITORING                        ║")
    logger.info("╚══════════════════════════════════════════════════════╝")
    logger.info("")

    def _sigterm(*_):
        # If finally block hangs (libcamera C threads can block), force-kill after 5 s
        threading.Timer(5.0, lambda: os.kill(os.getpid(), signal.SIGKILL)).start()
        sys.exit(0)
    signal.signal(signal.SIGTERM, _sigterm)

    _robot_armed     = False   # starts disarmed; press Start to arm
    _sim_emergency   = False   # set by joystick A; OR'd with real V2X — never overrides it
    _prev_h_state    = 'NORMAL'
    _stream_vx       = 0.0
    _stream_wz       = 0.0
    _last_stream_t   = 0.0
    _crop_y          = int(lc['crop_top_ratio'] * cc['height'])
    _run_log         = RunLogger(enabled=cfg.get('logging', {}).get('run_log', True))
    own_pos          = None    # last known position (survives frames where camera unavailable)

    try:
        while True:
            # ── Start button: arm / disarm toggle ────────────────────────
            # ── A button: simulate ambulance arrive (manual V2X test) ────
            # ── B button: simulate ambulance depart ──────────────────────
            # _sim_emergency is OR'd with bridge.is_emergency() so a real
            # V2X alert can never be suppressed by the joystick.
            if joystick.get_amb_arrive():
                _sim_emergency = True
                handler.set_force_yield(True)   # bypass position check for solo testing
                logger.info("*** SIM: ambulance ARRIVE (A button) ***")
            if joystick.get_amb_depart():
                _sim_emergency = False
                handler.set_force_yield(False)  # restore position logic
                # Note: if real V2X is still active, bridge.is_emergency() stays True
                # and position-based logic takes over — B cannot suppress a real ambulance.
                logger.info("*** SIM: ambulance DEPART (B button) ***")
            if joystick.get_train_toggle() and hasattr(follower, 'toggle_training'):
                follower.toggle_training()

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

            # ── Camera grab + stream — always runs regardless of arm state ──
            frame = cam.get_frame()

            if streamer and frame is not None:
                now = time.monotonic()
                if now - _last_stream_t >= 0.04:
                    _last_stream_t = now
                    panels = follower.get_roi_panels()
                    _push_stream(streamer, frame, panels, _crop_y,
                                 estimator, handler, bridge, broadcaster,
                                 joystick, _robot_armed, _stream_vx, _stream_wz,
                                 driver=driver, name=_robot_name)

            if not _robot_armed:
                if frame is None:
                    time.sleep(0.02)
                continue

            if frame is not None:
                # Position update (runs on every Nth frame inside estimator)
                estimator.process(frame)
                own_pos  = estimator.get_position()
                peer_pos = broadcaster.get_peer_position()
                broadcaster.set_own_position(own_pos)

                # Update emergency handler state
                handler.update_own_position(own_pos)
                handler.update_peer_position(peer_pos)
                handler.update_emergency(bridge.is_emergency() or _sim_emergency)

            # ── Zone sync — tell the follower which zone we're in ─────────
            zone = own_pos['zone'] if own_pos else -1
            follower.set_zone(zone)

            # ── Velocity decision — always runs, even without camera ──────
            js_cmd = joystick.get_command()
            if js_cmd is not None:
                # Joystick (deadman held) — bypass follower and emergency handler
                vx, wz = js_cmd
                # Record samples if training is active (recorded_path algorithm)
                if hasattr(follower, 'record') and follower.is_recording():
                    follower.record(vx, wz, zone)
            elif frame is not None:
                # Autonomous — lane following through emergency handler
                vx, wz = follower.process(frame)
                dbg = follower.get_debug_info()
                vx, wz = handler.process(
                    vx, wz,
                    boundary_near = follower.is_boundary_near(),
                    white_found   = (dbg.get('mode') == 'WHITE'),
                    yellow_cx     = dbg.get('yellow_cx'),
                    outer_tag     = estimator.is_off_track(),
                )
            else:
                # No camera, no joystick — hold stop
                vx, wz = 0.0, 0.0

            # When emergency handler enters RESUMING, reset follower LOST timers.
            # The no_white_stop_s timer accumulates during long evasion sequences
            # (EVADING up to 6s + HOLDING) and can expire before RESUMING starts,
            # causing the follower to return (0,0) immediately on ramp-up.
            new_h_state = handler.get_state()
            if _prev_h_state != 'RESUMING' and new_h_state == 'RESUMING':
                follower.reset_pid()
                logger.info("Entering RESUMING — follower LOST timers reset")
            _prev_h_state = new_h_state

            driver.set_velocity(vx, wz)
            _stream_vx, _stream_wz = vx, wz

            # ── Run log (10 Hz, only while armed) ────────────────────────
            _run_log.log(vx, wz, zone, follower, estimator, driver,
                         handler=handler,
                         emergency=bridge.is_emergency() or _sim_emergency)

            if frame is None:
                time.sleep(0.02)  # ~50 Hz when no camera

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
