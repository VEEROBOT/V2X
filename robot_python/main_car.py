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
import logging
import os
import signal
import sys
import threading
import time

import yaml

from camera               import Camera
from joystick             import Joystick
from robot_driver         import RobotDriver
from lane_follower        import LaneFollower
from position             import PositionEstimator
from position_broadcaster import PositionBroadcaster
from v2x_bridge           import V2XBridge
from emergency_handler    import EmergencyHandler
from control_socket       import ControlSocket

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('car')


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


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

    cfg = load_config(args.config)

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
    )
    driver.start()
    time.sleep(1.0)   # wait for STM32 ROS-mode init
    driver.arm()

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
    follower = LaneFollower(
        linear_speed=lc['linear_speed'],
        max_angular_speed=lc['max_angular_speed'],
        crop_top_ratio=lc['crop_top_ratio'],
        min_contour_area=lc['min_contour_area'],
        kp=lc['kp'], ki=lc['ki'], kd=lc['kd'],
        lane_offset_px=lc['lane_offset_px'],
        white_hsv_low =(lc['white_h_low'],  lc['white_s_low'],  lc['white_v_low']),
        white_hsv_high=(lc['white_h_high'], lc['white_s_high'], lc['white_v_high']),
        yellow_hsv_low =(lc['yellow_h_low'],  lc['yellow_s_low'],  lc['yellow_v_low']),
        yellow_hsv_high=(lc['yellow_h_high'], lc['yellow_s_high'], lc['yellow_v_high']),
        debug=args.debug_image or lc.get('debug_image', False),
    )

    # ── Position estimator + broadcaster ─────────────────────────────────
    pc = cfg['position']
    estimator = PositionEstimator(
        n_tags=pc['n_tags'],
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
        evasion_linear_speed=ec['evasion_linear_speed'],
        evasion_angular_speed=ec['evasion_angular_speed'],
        evasion_duration_s=ec['evasion_duration_s'],
        hold_timeout_s=ec['hold_timeout_s'],
        clear_delay_s=ec['clear_delay_s'],
        resume_ramp_duration_s=ec['resume_ramp_duration_s'],
        n_tags=ec['n_tags'],
        yield_zone_gap=ec['yield_zone_gap'],
        position_timeout_s=ec['position_timeout_s'],
    )

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

    _robot_armed = True   # starts armed; Start button toggles

    try:
        while True:
            # ── Start button: arm / disarm toggle ────────────────────────
            if joystick.get_arm_press():
                _robot_armed = not _robot_armed
                if _robot_armed:
                    driver.arm()
                    logger.info("*** ARMED (Start button) ***")
                else:
                    driver.set_velocity(0.0, 0.0)
                    driver.disarm()
                    logger.info("*** DISARMED (Start button) ***")

            if not _robot_armed:
                time.sleep(0.02)
                continue

            frame = cam.get_frame()

            if frame is not None:
                # Position update (runs on every Nth frame inside estimator)
                estimator.process(frame)
                own_pos  = estimator.get_position()
                peer_pos = broadcaster.get_peer_position()
                broadcaster.set_own_position(own_pos)

                # Update emergency handler state
                handler.update_own_position(own_pos)
                handler.update_peer_position(peer_pos)
                handler.update_emergency(bridge.is_emergency())

            # ── Velocity decision — always runs, even without camera ──────
            js_cmd = joystick.get_command()
            if js_cmd is not None:
                # Joystick (deadman held) — bypass lane follower and emergency handler
                vx, wz = js_cmd
            elif frame is not None:
                # Autonomous — lane following through emergency handler
                vx, wz = follower.process(frame)
                vx, wz = handler.process(vx, wz)
            else:
                # No camera, no joystick — hold stop
                vx, wz = 0.0, 0.0

            driver.set_velocity(vx, wz)

            if frame is None:
                time.sleep(0.02)  # ~50 Hz when no camera

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
