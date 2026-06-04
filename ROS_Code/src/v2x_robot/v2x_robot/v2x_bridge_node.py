#!/usr/bin/env python3
"""
V2X Bridge node — connects V2X infrastructure to ROS2.

Two operation paths:

1. MANUAL MODE (default — no OBU binary needed):
   Use /v2x/set_emergency service to simulate emergency for testing.

2. OBU MODE (auto-enabled when obu_binary param is a valid file path):
   Spawns ./obu_client <config> --loop 999999 as a subprocess.
   Ambulance OBU → RSU authenticates → RSU sends UDP alert to car.

3. RSU ALERT LISTENER (car role only — always active in OBU mode):
   Listens on UDP car_alert_port for {"type":"EMERGENCY_ACTIVE"} /
   {"type":"EMERGENCY_CLEARED"} notifications from RSU.
   This is how the full V2X loop closes: ambulance → RSU → UDP → car.

OBU CLI reference (obu/src/main.cpp):
  ./obu_client [config_path] [--loop N]
  Config is a positional argument, NOT --config.

OBU stdout keywords used:
  Emergency active  → "Emergency priority flag sent"
  Auth failed       → "[OBU] FAILED:"

Topics
  Pub  /v2x/emergency_detected  std_msgs/Bool   (5 Hz)

Services
  /v2x/set_emergency  std_srvs/SetBool  — manual trigger / testing
  /v2x/get_status     std_srvs/Trigger  — returns current state string
"""

import json
import os
import socket
import subprocess
import threading
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool
from std_srvs.srv import SetBool, Trigger


_OBU_EMERGENCY_SENT = "Emergency priority flag sent"
_OBU_AUTH_FAILED    = "[OBU] FAILED:"


class V2XBridgeNode(Node):

    def __init__(self):
        super().__init__('v2x_bridge')

        # ── Parameters ─────────────────────────────────────────────────────
        self.declare_parameter('role',               'car')   # 'car' | 'ambulance'
        self.declare_parameter('obu_binary',         '')      # path to obu_client binary
        self.declare_parameter('obu_config',         '')      # path to obu JSON config
        self.declare_parameter('manual_mode',        True)    # overridden automatically if binary exists
        self.declare_parameter('publish_rate_hz',    5.0)
        self.declare_parameter('exit_clear_delay_s', 5.0)    # seconds after OBU exits to clear emergency
        self.declare_parameter('car_alert_port',     5001)   # UDP port to listen for RSU alerts (car role)

        self._role             = self.get_parameter('role').value
        self._obu_binary       = self.get_parameter('obu_binary').value
        self._obu_config       = self.get_parameter('obu_config').value
        self._manual_mode      = self.get_parameter('manual_mode').value
        rate                   = self.get_parameter('publish_rate_hz').value
        self._exit_clear_delay = self.get_parameter('exit_clear_delay_s').value
        self._car_alert_port   = self.get_parameter('car_alert_port').value

        # Auto-disable manual mode when a valid binary path is supplied
        if self._obu_binary and os.path.isfile(self._obu_binary):
            self._manual_mode = False
            self.get_logger().info("OBU binary found — switching to OBU mode")

        # ── State ──────────────────────────────────────────────────────────
        self._emergency  = False
        self._obu_proc   = None
        self._running    = True

        # ── ROS I/O ────────────────────────────────────────────────────────
        self._pub = self.create_publisher(Bool, '/v2x/emergency_detected', 10)
        self.create_service(SetBool, '/v2x/set_emergency', self._svc_set_emergency)
        self.create_service(Trigger, '/v2x/get_status',    self._svc_get_status)
        self.create_timer(1.0 / rate, self._publish)

        # ── Start OBU or stay manual ───────────────────────────────────────
        if not self._manual_mode:
            self._start_obu()
            # Car listens for RSU UDP alerts; ambulance only sends via OBU
            if self._role == 'car':
                self._start_rsu_listener()
        else:
            self.get_logger().info(
                f"V2X bridge [{self._role}] MANUAL mode\n"
                "  Trigger: ros2 service call /v2x/set_emergency "
                "std_srvs/srv/SetBool '{data: true}'"
            )

    # ──────────────────────────────────────────────────────────────────────
    # OBU subprocess
    # ──────────────────────────────────────────────────────────────────────
    def _build_obu_cmd(self) -> list:
        # OBU CLI: ./obu_client [config_path] [--loop N]
        cmd = [self._obu_binary]
        if self._obu_config:
            cmd.append(self._obu_config)   # positional — NOT --config
        cmd += ['--loop', '999999']        # run continuously
        return cmd

    def _start_obu(self):
        if not self._obu_binary or not os.path.isfile(self._obu_binary):
            self.get_logger().error(
                f"OBU binary not found: '{self._obu_binary}' — falling back to manual mode"
            )
            self._manual_mode = True
            return

        cmd = self._build_obu_cmd()
        self.get_logger().info(f"Starting OBU: {' '.join(cmd)}")
        try:
            self._obu_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            threading.Thread(target=self._tail_obu, daemon=True).start()
            self.get_logger().info(f"OBU process started  pid={self._obu_proc.pid}")
        except Exception as exc:
            self.get_logger().error(f"Failed to start OBU: {exc} — falling back to manual mode")
            self._manual_mode = True

    def _tail_obu(self):
        """Background thread: read OBU stdout and parse events."""
        for line in self._obu_proc.stdout:
            if not self._running:
                break
            line = line.rstrip()
            if line:
                self.get_logger().info(f"[OBU] {line}", throttle_duration_sec=0.5)

            # Ambulance OBU successfully sent emergency auth
            if _OBU_EMERGENCY_SENT in line:
                if not self._emergency:
                    self.get_logger().warn("Emergency V2X signal confirmed by OBU")
                self._emergency = True

            elif _OBU_AUTH_FAILED in line:
                self.get_logger().error(f"OBU auth failed: {line}")

        # OBU process exited
        if self._running:
            rc = self._obu_proc.wait()
            self.get_logger().warn(
                f"OBU process exited (rc={rc}). "
                f"Emergency will clear in {self._exit_clear_delay:.0f}s."
            )
            time.sleep(self._exit_clear_delay)
            if self._emergency:
                self.get_logger().info("Clearing emergency after OBU exit")
                self._emergency = False

    # ──────────────────────────────────────────────────────────────────────
    # RSU UDP alert listener (car role only)
    # ──────────────────────────────────────────────────────────────────────
    def _start_rsu_listener(self):
        """Listen for UDP alerts from RSU on car_alert_port.

        RSU sends:
          {"type": "EMERGENCY_ACTIVE",  "session_id": "..."}
          {"type": "EMERGENCY_CLEARED"}
        """
        threading.Thread(target=self._rsu_listen_loop, daemon=True).start()
        self.get_logger().info(
            f"RSU alert listener started on UDP port {self._car_alert_port}"
        )

    def _rsu_listen_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)
        try:
            sock.bind(('0.0.0.0', self._car_alert_port))
        except OSError as e:
            self.get_logger().error(f"Cannot bind RSU alert socket: {e}")
            return

        while self._running:
            try:
                data, addr = sock.recvfrom(1024)
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    self.get_logger().error(f"RSU listener error: {e}", throttle_duration_sec=5.0)
                continue

            try:
                msg = json.loads(data.decode('utf-8'))
                alert_type = msg.get('type', '')

                if alert_type == 'EMERGENCY_ACTIVE':
                    sid = msg.get('session_id', '')
                    self.get_logger().warn(
                        f"RSU ALERT: EMERGENCY ACTIVE (session={sid[:8]}...) from {addr[0]}"
                    )
                    self._emergency = True

                elif alert_type == 'EMERGENCY_CLEARED':
                    self.get_logger().info(f"RSU ALERT: Emergency cleared (from {addr[0]})")
                    self._emergency = False

                else:
                    self.get_logger().warn(f"RSU listener: unknown alert type '{alert_type}'")

            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                self.get_logger().warn(f"RSU listener: malformed packet from {addr}: {e}")

        sock.close()

    # ──────────────────────────────────────────────────────────────────────
    # Services
    # ──────────────────────────────────────────────────────────────────────
    def _svc_set_emergency(self, request, response):
        """Manual service — always works regardless of OBU mode."""
        self._emergency = request.data
        state = 'ACTIVE' if request.data else 'CLEARED'
        self.get_logger().warn(f"Emergency manually set: {state}")
        response.success = True
        response.message = f"Emergency {state}"
        return response

    def _svc_get_status(self, request, response):
        mode = 'manual' if self._manual_mode else 'obu'
        pid  = self._obu_proc.pid if self._obu_proc else 'n/a'
        response.success = True
        response.message = (
            f"role={self._role}  "
            f"emergency={'ACTIVE' if self._emergency else 'CLEAR'}  "
            f"mode={mode}  obu_pid={pid}"
        )
        return response

    # ──────────────────────────────────────────────────────────────────────
    def _publish(self):
        msg = Bool()
        msg.data = self._emergency
        self._pub.publish(msg)

    # ──────────────────────────────────────────────────────────────────────
    def destroy_node(self):
        self._running = False
        if self._obu_proc and self._obu_proc.poll() is None:
            self._obu_proc.terminate()
            try:
                self._obu_proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._obu_proc.kill()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = V2XBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()


if __name__ == '__main__':
    main()
