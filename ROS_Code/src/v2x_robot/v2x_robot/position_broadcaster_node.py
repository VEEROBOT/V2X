#!/usr/bin/env python3
"""
Position broadcaster — peer-to-peer road-position sharing over UDP.

Reads own position from /robot/position (set by position_node) and broadcasts it
to the peer robot at peer_ip:peer_port every broadcast_hz seconds.
Simultaneously listens for the peer's broadcasts and re-publishes them as
/v2x/peer_position so other nodes (e.g. emergency_handler_node) can compare.

This node is the TRANSPORT layer.  It does not make any control decisions.
It runs on both robots with mirror-image peer_ip configuration:
  Car launch      → peer_ip = ambulance IP, role = car
  Ambulance launch → peer_ip = car IP,       role = ambulance

UDP message format (JSON):
  {"type": "POSITION", "zone": 5, "distance_m": 0.23, "role": "ambulance"}

Topics
  Sub  /robot/position    std_msgs/String  (from position_node)
  Pub  /v2x/peer_position std_msgs/String  (received from peer robot)

Parameters
  peer_ip       str    IP or hostname of the other robot (empty = disabled)
  peer_port     int    UDP port used by BOTH robots for position exchange (default 5002)
  broadcast_hz  float  How many times per second to send own position (default 10.0)
  role          str    'car' | 'ambulance' — appended to outgoing packet
"""

import json
import socket
import threading

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class PositionBroadcasterNode(Node):

    def __init__(self):
        super().__init__('position_broadcaster')

        self.declare_parameter('peer_ip',      '')
        self.declare_parameter('peer_port',    5002)
        self.declare_parameter('broadcast_hz', 10.0)
        self.declare_parameter('role',         'car')

        p = self.get_parameter
        self._peer_ip    = p('peer_ip').value
        self._peer_port  = p('peer_port').value
        self._role       = p('role').value
        rate             = float(p('broadcast_hz').value)

        # ── State ──────────────────────────────────────────────────────────
        self._own_position_json = ''   # raw JSON string from /robot/position
        self._running           = True

        # ── ROS I/O ────────────────────────────────────────────────────────
        self.create_subscription(String, '/robot/position', self._position_cb, 10)
        self._peer_pub = self.create_publisher(String, '/v2x/peer_position', 10)

        if not self._peer_ip:
            self.get_logger().warn(
                "Position broadcaster: peer_ip not set — position sharing disabled.\n"
                "  Set peer_ip in launch file to enable peer-to-peer position sharing."
            )
            return

        # ── UDP send socket ────────────────────────────────────────────────
        self._send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # ── Start listener thread ──────────────────────────────────────────
        threading.Thread(target=self._listen_loop, daemon=True).start()
        self.get_logger().info(
            f"Position broadcaster  peer={self._peer_ip}:{self._peer_port}  "
            f"role={self._role}  rate={rate:.0f}Hz"
        )

        # ── Broadcast timer ────────────────────────────────────────────────
        self.create_timer(1.0 / rate, self._broadcast)

    # ──────────────────────────────────────────────────────────────────────
    def _position_cb(self, msg: String):
        self._own_position_json = msg.data

    # ──────────────────────────────────────────────────────────────────────
    def _broadcast(self):
        """Send own position to peer. Called at broadcast_hz."""
        if not self._peer_ip or not self._own_position_json:
            return
        try:
            data   = json.loads(self._own_position_json)
            packet = json.dumps({
                'type':       'POSITION',
                'zone':       data.get('zone', -1),
                'distance_m': data.get('distance_m', 0.0),
                'role':       self._role,
            })
            self._send_sock.sendto(packet.encode('utf-8'),
                                   (self._peer_ip, self._peer_port))
        except Exception as e:
            self.get_logger().error(f"Broadcast error: {e}", throttle_duration_sec=5.0)

    # ──────────────────────────────────────────────────────────────────────
    def _listen_loop(self):
        """Background thread: listen for peer position broadcasts."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)
        try:
            sock.bind(('0.0.0.0', self._peer_port))
        except OSError as e:
            self.get_logger().error(f"Cannot bind position listener: {e}")
            return

        while self._running:
            try:
                raw, addr = sock.recvfrom(512)
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    self.get_logger().error(f"Listener error: {e}", throttle_duration_sec=5.0)
                continue

            try:
                msg = json.loads(raw.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

            if msg.get('type') != 'POSITION':
                continue
            if msg.get('role') == self._role:
                continue    # echo of own broadcast (shouldn't happen on separate IPs)

            out = String()
            out.data = json.dumps({
                'zone':       msg.get('zone', -1),
                'distance_m': msg.get('distance_m', 0.0),
            })
            self._peer_pub.publish(out)

        sock.close()

    # ──────────────────────────────────────────────────────────────────────
    def destroy_node(self):
        self._running = False
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = PositionBroadcasterNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()


if __name__ == '__main__':
    main()
