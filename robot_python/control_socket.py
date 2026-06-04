#!/usr/bin/env python3
"""
UDP control socket — manual command interface.

Replaces ROS2 service calls for testing without OBU hardware.
Listens on localhost:<port> for JSON commands.

Supported commands:
  {"cmd": "emergency_on"}
  {"cmd": "emergency_off"}
  {"cmd": "arm"}
  {"cmd": "disarm"}
  {"cmd": "estop"}
  {"cmd": "status"}

Send from another terminal:
  python3 -c "import socket,json; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.sendto(json.dumps({'cmd':'emergency_on'}).encode(), ('127.0.0.1', 5010))"
  # or use the helper:
  python3 control_socket.py --port 5010 emergency_on
"""

import json
import logging
import socket
import threading

logger = logging.getLogger(__name__)


class ControlSocket:
    """Listens for UDP JSON commands and dispatches to registered handlers."""

    def __init__(self, port: int = 5010):
        self._port     = port
        self._handlers = {}
        self._running  = False

    def register(self, cmd: str, fn):
        self._handlers[cmd] = fn

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True, name='ctrl_sock').start()
        logger.info("Control socket listening on UDP port %d", self._port)

    def stop(self):
        self._running = False

    def _loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)
        try:
            sock.bind(('0.0.0.0', self._port))   # 0.0.0.0 = accept from any machine on the network
        except OSError as e:
            logger.error("Cannot bind control socket on port %d: %s", self._port, e)
            return

        while self._running:
            try:
                data, addr = sock.recvfrom(256)
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    logger.error("Control socket error: %s", e)
                continue

            try:
                msg = json.loads(data.decode('utf-8'))
                cmd = msg.get('cmd', '')
                if cmd in self._handlers:
                    self._handlers[cmd]()
                else:
                    logger.warning("Control socket: unknown command '%s'", cmd)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.warning("Control socket: bad packet: %s", e)

        sock.close()


# ── CLI helper ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import sys
    import argparse

    p = argparse.ArgumentParser(description='Send a control command to a running robot')
    p.add_argument('command', choices=[
        'emergency_on', 'emergency_off', 'arm', 'disarm', 'estop', 'status'])
    p.add_argument('--port', type=int, default=5010,
                   help='Control socket port (car=5010, ambulance=5011)')
    p.add_argument('--host', default='127.0.0.1')
    args = p.parse_args()

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.sendto(json.dumps({'cmd': args.command}).encode('utf-8'), (args.host, args.port))
    print(f"Sent '{args.command}' to {args.host}:{args.port}")
