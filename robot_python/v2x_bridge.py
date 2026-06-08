#!/usr/bin/env python3
"""
V2X bridge — connects V2X infrastructure to the robot stack.

Two operation modes selected at startup:

  MANUAL (default, manual_mode=True):
    No OBU binary. Use the UDP control socket or set_emergency() directly.
    Useful for integration testing without real V2X hardware.

  OBU (manual_mode=False or auto-detected when obu_binary path exists):
    Spawns ./obu_client <config> --loop <obu_loop_count> as a subprocess.
    Car:       obu_loop_count=1  — authenticate once, session lasts 300s, OBU exits.
    Ambulance: obu_loop_count=0  — loop forever until service is stopped.
    Ambulance: OBU authenticates with RSU → RSU sends UDP alert to car.
    Car: listens on car_alert_port for RSU JSON notifications.

Public API:
  bridge.start()
  bridge.stop()
  bridge.set_emergency(True/False)   — manual override (always works)
  bridge.is_emergency() → bool
"""

import json
import logging
import os
import socket
import subprocess
import threading
import time

logger = logging.getLogger(__name__)

_OBU_EMERGENCY_SENT = "Emergency priority flag sent"
_OBU_AUTH_FAILED    = "[OBU] FAILED:"


class V2XBridge:

    def __init__(self,
                 role: str = 'car',
                 obu_binary: str = '',
                 obu_config: str = '',
                 manual_mode: bool = True,
                 car_alert_port: int = 5001,
                 exit_clear_delay_s: float = 5.0,
                 obu_loop_count: int = 1):

        self._role             = role
        self._obu_binary       = obu_binary
        self._obu_config       = obu_config
        self._manual_mode      = manual_mode
        self._car_alert_port   = car_alert_port
        self._exit_clear_delay = exit_clear_delay_s
        self._obu_loop_count   = obu_loop_count

        # Auto-detect OBU binary
        if self._obu_binary and os.path.isfile(self._obu_binary):
            self._manual_mode = False
            logger.info("OBU binary found — switching to OBU mode")

        self._emergency = False
        self._obu_proc  = None
        self._running   = False

    def start(self):
        if self._running:
            return
        self._running = True

        if not self._manual_mode:
            self._start_obu()
            if self._role == 'car':
                self._start_rsu_listener()
        else:
            logger.info("V2X bridge [%s] MANUAL mode — use set_emergency() or UDP control",
                        self._role)

    def stop(self):
        self._running = False
        if self._obu_proc and self._obu_proc.poll() is None:
            self._obu_proc.terminate()
            try:
                self._obu_proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._obu_proc.kill()

    def set_emergency(self, active: bool):
        self._emergency = active
        logger.warning("Emergency manually set: %s", "ACTIVE" if active else "CLEARED")

    def is_emergency(self) -> bool:
        return self._emergency

    def status(self) -> str:
        mode = 'manual' if self._manual_mode else 'obu'
        pid  = self._obu_proc.pid if self._obu_proc else 'n/a'
        return (f"role={self._role}  "
                f"emergency={'ACTIVE' if self._emergency else 'CLEAR'}  "
                f"mode={mode}  obu_pid={pid}")

    # ── OBU subprocess ───────────────────────────────────────────────────────
    def _start_obu(self):
        if not self._obu_binary or not os.path.isfile(self._obu_binary):
            logger.error("OBU binary not found: '%s' — falling back to manual mode",
                         self._obu_binary)
            self._manual_mode = True
            return

        cmd = [self._obu_binary]
        if self._obu_config:
            cmd.append(self._obu_config)
        loop = '999999' if self._obu_loop_count <= 0 else str(self._obu_loop_count)
        cmd += ['--loop', loop]

        logger.info("Starting OBU: %s", ' '.join(cmd))
        try:
            self._obu_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            threading.Thread(target=self._tail_obu, daemon=True, name='obu_tail').start()
            logger.info("OBU process started  pid=%d", self._obu_proc.pid)
        except Exception as e:
            logger.error("Failed to start OBU: %s — falling back to manual mode", e)
            self._manual_mode = True

    def _tail_obu(self):
        for line in self._obu_proc.stdout:
            if not self._running:
                break
            line = line.rstrip()
            if line:
                logger.info("[OBU] %s", line)
            if _OBU_EMERGENCY_SENT in line:
                if not self._emergency:
                    logger.warning("Emergency V2X signal confirmed by OBU")
                self._emergency = True
            elif _OBU_AUTH_FAILED in line:
                logger.error("OBU auth failed: %s", line)

        if self._running:
            rc = self._obu_proc.wait()
            logger.warning("OBU process exited (rc=%d). Emergency clears in %.0fs.",
                           rc, self._exit_clear_delay)
            time.sleep(self._exit_clear_delay)
            if self._emergency:
                logger.info("Clearing emergency after OBU exit")
                self._emergency = False

    # ── RSU UDP alert listener (car role) ────────────────────────────────────
    def _start_rsu_listener(self):
        threading.Thread(target=self._rsu_loop, daemon=True, name='rsu_listener').start()
        logger.info("RSU alert listener started on UDP port %d", self._car_alert_port)

    def _rsu_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)
        try:
            sock.bind(('0.0.0.0', self._car_alert_port))
        except OSError as e:
            logger.error("Cannot bind RSU alert socket on port %d: %s",
                         self._car_alert_port, e)
            return

        while self._running:
            try:
                data, addr = sock.recvfrom(1024)
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    logger.error("RSU listener error: %s", e)
                continue

            try:
                msg = json.loads(data.decode('utf-8'))
                t   = msg.get('type', '')
                if t == 'EMERGENCY_ACTIVE':
                    sid = msg.get('session_id', '')
                    logger.warning("RSU ALERT: EMERGENCY ACTIVE (session=%s) from %s",
                                   sid[:8], addr[0])
                    self._emergency = True
                elif t == 'EMERGENCY_CLEARED':
                    logger.info("RSU ALERT: Emergency cleared from %s", addr[0])
                    self._emergency = False
                else:
                    logger.warning("RSU listener: unknown type '%s'", t)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.warning("RSU listener: malformed packet: %s", e)

        sock.close()
