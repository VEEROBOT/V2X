#!/usr/bin/env python3
"""
Robot driver — thin wrapper around the Lyra binary protocol.

Manages serial communication with the STM32 motor controller.
Runs three internal timers in a single background thread:
  - 20 Hz: send current velocity command (or zero if stale / disarmed)
  - 10 Hz: request telemetry
  -  1 Hz: send heartbeat

Public API (thread-safe):
  driver.arm()
  driver.disarm()
  driver.estop()
  driver.set_velocity(vx, wz)   — stores command; motor loop sends it at 20 Hz
  driver.get_telemetry()         — returns last parsed telemetry dict or None
  driver.is_armed()
  driver.is_connected()
  driver.start() / driver.stop()
"""

import logging
import threading
import time

from lib.protocol import (
    build_arm_command,
    build_disarm_command,
    build_emergency_stop_command,
    build_get_telemetry_command,
    build_heartbeat_command,
    build_set_ros_mode_command,
    build_set_wheel_vel_command,
    parse_from_buffer,
    CMD_GET_TELEMETRY,
)
from lib.transport import SerialTransport
from lib.telemetry import parse_telemetry, parse_status_flags

logger = logging.getLogger(__name__)

# Loop intervals
_MOTOR_HZ       = 20
_TELEM_HZ       = 10
_HEARTBEAT_HZ   = 1
_RX_HZ          = 50

_CMD_TIMEOUT_S  = 0.5


class RobotDriver:

    def __init__(self, port: str = '/dev/ttyAMA0', baudrate: int = 115200,
                 wheel_radius: float = 0.065,
                 track_width: float = 0.377,
                 max_wheel_speed: float = 15.7,
                 cmd_timeout: float = _CMD_TIMEOUT_S):

        self._wheel_radius    = wheel_radius
        self._track_width     = track_width
        self._max_wheel_speed = max_wheel_speed
        self._cmd_timeout     = cmd_timeout

        self._transport = SerialTransport(port, baudrate, timeout=0.0)

        # Sequence number (0–255, wraps)
        self._seq      = 0
        self._seq_lock = threading.Lock()

        # Velocity command
        self._vx           = 0.0
        self._wz           = 0.0
        self._cmd_time     = 0.0          # monotonic time of last set_velocity call
        self._cmd_lock     = threading.Lock()

        # State
        self._armed        = False
        self._armed_lock   = threading.Lock()
        self._last_telem   = None
        self._telem_lock   = threading.Lock()
        self._ros_mode_ok  = False

        self._running      = False
        self._thread       = None

    # ── Public lifecycle ────────────────────────────────────────────────────
    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name='robot_driver')
        self._thread.start()
        logger.info("RobotDriver started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        self._transport.close()
        logger.info("RobotDriver stopped")

    # ── Public commands ─────────────────────────────────────────────────────
    def arm(self):
        self._send(build_arm_command(self._next_seq()))
        logger.info("ARM command sent")

    def disarm(self):
        self._send(build_disarm_command(self._next_seq()))
        logger.info("DISARM command sent")

    def estop(self):
        self._send(build_emergency_stop_command(self._next_seq()))
        logger.warning("EMERGENCY STOP sent")

    def set_velocity(self, vx: float, wz: float):
        with self._cmd_lock:
            self._vx       = vx
            self._wz       = wz
            self._cmd_time = time.monotonic()

    # ── Public getters ──────────────────────────────────────────────────────
    def get_telemetry(self):
        with self._telem_lock:
            return self._last_telem

    def is_armed(self) -> bool:
        with self._armed_lock:
            return self._armed

    def is_connected(self) -> bool:
        return self._transport.is_connected()

    # ── Background loop ─────────────────────────────────────────────────────
    def _loop(self):
        t_motor     = 0.0
        t_telem     = 0.0
        t_heartbeat = 0.0
        t_rx        = 0.0

        # Send SET_ROS_MODE once after a short delay so STM32 has booted
        time.sleep(0.5)
        self._send(build_set_ros_mode_command(self._next_seq(), True))
        self._ros_mode_ok = True
        logger.info("ROS mode enabled")

        while self._running:
            now = time.monotonic()

            # RX poll (50 Hz)
            if now - t_rx >= 1.0 / _RX_HZ:
                t_rx = now
                self._rx_poll()

            # Telemetry request (10 Hz)
            if now - t_telem >= 1.0 / _TELEM_HZ:
                t_telem = now
                self._send(build_get_telemetry_command(self._next_seq()))

            # Heartbeat (1 Hz)
            if now - t_heartbeat >= 1.0 / _HEARTBEAT_HZ:
                t_heartbeat = now
                self._send(build_heartbeat_command(self._next_seq()))

            # Motor control (20 Hz)
            if now - t_motor >= 1.0 / _MOTOR_HZ:
                t_motor = now
                self._motor_tick(now)

            time.sleep(0.002)  # 2 ms resolution

    def _motor_tick(self, now: float):
        with self._armed_lock:
            armed = self._armed

        with self._cmd_lock:
            vx        = self._vx
            wz        = self._wz
            cmd_age   = now - self._cmd_time

        if not armed or cmd_age > self._cmd_timeout:
            if not armed:
                pass  # silent when disarmed
            elif cmd_age > self._cmd_timeout:
                logger.warning(f"cmd_vel timeout ({cmd_age:.2f}s) — stopping")
            self._send(build_set_wheel_vel_command(self._next_seq(), [0.0]*4))
            return

        wheels = self._ik(vx, wz)
        self._send(build_set_wheel_vel_command(self._next_seq(), wheels))

    def _rx_poll(self):
        self._transport.poll()
        buf = self._transport.get_buffer()
        while True:
            result = parse_from_buffer(buf)
            if result is None:
                break
            _, cmd, payload = result
            if cmd == CMD_GET_TELEMETRY:
                telem = parse_telemetry(payload)
                if telem:
                    flags = parse_status_flags(telem['status_flags'])
                    with self._armed_lock:
                        prev = self._armed
                        self._armed = flags['armed']
                        if self._armed != prev:
                            logger.info("Robot %s", "ARMED" if self._armed else "DISARMED")
                    with self._telem_lock:
                        self._last_telem = telem

    # ── Helpers ─────────────────────────────────────────────────────────────
    def _next_seq(self) -> int:
        with self._seq_lock:
            self._seq = (self._seq + 1) % 256
            return self._seq

    def _send(self, frame: bytes):
        self._transport.write(frame)

    def _ik(self, vx: float, wz: float) -> list:
        half = self._track_width / 2.0
        v_l  = vx - wz * half
        v_r  = vx + wz * half
        w_l  = max(min(v_l / self._wheel_radius, self._max_wheel_speed), -self._max_wheel_speed)
        w_r  = max(min(v_r / self._wheel_radius, self._max_wheel_speed), -self._max_wheel_speed)
        return [w_l, w_l, w_r, w_r]  # [FL, BL, BR, FR]
