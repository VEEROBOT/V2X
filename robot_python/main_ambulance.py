#!/usr/bin/env python3
"""
V2X Ambulance Robot — pure Python main loop.

Simpler than the car: no emergency handler — the ambulance drives through.
Runs faster (linear_speed = 0.28 m/s hard-coded here, overrides config).

Usage:
  python3 main_ambulance.py
  python3 main_ambulance.py --car-ip 192.168.1.x
  python3 main_ambulance.py --debug-image
  python3 main_ambulance.py --obu-binary /home/pi/v2x/obu/build/obu_client \\
                            --obu-config  /home/pi/v2x/obu/config/obu2_config.json \\
                            --car-ip 192.168.1.x

Trigger emergency broadcast (manual mode, from another terminal):
  python3 control_socket.py --port 5011 emergency_on
  python3 control_socket.py --port 5011 emergency_off
"""

import argparse
import logging
import sys
import time

import yaml

from camera               import Camera
from joystick             import Joystick
from robot_driver         import RobotDriver
from lane_follower        import LaneFollower
from position             import PositionEstimator
from position_broadcaster import PositionBroadcaster
from v2x_bridge           import V2XBridge
from control_socket       import ControlSocket

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('ambulance')

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

    # ── Robot driver ─────────────────────────────────────────────────────
    rc = cfg['robot']
    sc = cfg['serial']
    driver = RobotDriver(
        port=args.serial_port or sc['port'],
        baudrate=sc['baudrate'],
        wheel_radius=rc['wheel_radius_m'],
        track_width=rc['track_width_m'],
        max_wheel_speed=rc['max_wheel_speed_rad_s'],
        cmd_timeout=rc['cmd_vel_timeout_s'],
    )
    driver.start()
    time.sleep(1.0)
    driver.arm()

    # ── Camera ────────────────────────────────────────────────────────────
    cc = cfg['camera']
    cam = Camera(
        device=cc['device'],
        width=cc['width'],
        height=cc['height'],
        use_picamera2=cc.get('use_picamera2', True),
    )
    if not cam.start():
        logger.error("Camera failed to open — exiting")
        driver.stop()
        sys.exit(1)

    # ── Joystick ──────────────────────────────────────────────────────────
    jc = cfg.get('joystick', {})
    joystick = Joystick(
        device_index=jc.get('device_index', 0),
        deadman_button=jc.get('deadman_button', 5),
        axis_throttle=jc.get('axis_throttle', 1),
        axis_steering=jc.get('axis_steering', 3),
        max_speed=jc.get('max_speed', 0.4),
        max_steering=jc.get('max_steering', 1.5),
        deadzone=jc.get('deadzone', 0.10),
    )
    joystick.start()

    # ── Lane follower ─────────────────────────────────────────────────────
    lc = cfg['lane_follower']
    follower = LaneFollower(
        linear_speed=lc['linear_speed'],
        max_angular_speed=lc['max_angular_speed'],
        crop_top_ratio=lc['crop_top_ratio'],
        min_contour_area=lc['min_contour_area'],
        kp=lc['kp'], ki=lc['ki'], kd=lc['kd'],
        lane_offset_px=0,   # ambulance follows white centre line directly
        white_hsv_low =(lc['white_h_low'],  lc['white_s_low'],  lc['white_v_low']),
        white_hsv_high=(lc['white_h_high'], lc['white_s_high'], lc['white_v_high']),
        yellow_hsv_low =(lc['yellow_h_low'],  lc['yellow_s_low'],  lc['yellow_v_low']),
        yellow_hsv_high=(lc['yellow_h_high'], lc['yellow_s_high'], lc['yellow_v_high']),
        debug=args.debug_image or lc.get('debug_image', False),
    )

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

    pbc    = cfg['position_broadcaster']
    car_ip = args.car_ip or pbc.get('peer_ip', '')
    broadcaster = PositionBroadcaster(
        peer_ip=car_ip,
        peer_port=pbc['peer_port'],
        broadcast_hz=pbc['broadcast_hz'],
        role='ambulance',
    )
    broadcaster.start()

    # ── V2X bridge ────────────────────────────────────────────────────────
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

    # ── Control socket ────────────────────────────────────────────────────
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
                "CONNECTED (hold btn%d to drive)" % jc.get('deadman_button', 5)
                if joystick.connected() else "not found — autonomous only          ║")
    logger.info("║  V2X broadcast   : STANDBY (manual mode)             ║")
    logger.info("╚══════════════════════════════════════════════════════╝")
    logger.info("")

    try:
        while True:
            frame = cam.get_frame()
            if frame is None:
                time.sleep(0.05)
                continue

            # Position update + broadcast
            estimator.process(frame)
            own_pos = estimator.get_position()
            broadcaster.set_own_position(own_pos)

            # ── Velocity decision ─────────────────────────────────────────
            js_cmd = joystick.get_command()
            if js_cmd is not None:
                vx, wz = js_cmd
            else:
                vx, wz = follower.process(frame)

            driver.set_velocity(vx, wz)

    except KeyboardInterrupt:
        logger.info("Shutting down…")
    finally:
        driver.set_velocity(0.0, 0.0)
        time.sleep(0.1)
        driver.disarm()
        driver.stop()
        bridge.stop()
        broadcaster.stop()
        joystick.stop()
        ctrl.stop()
        cam.stop()


if __name__ == '__main__':
    main()
