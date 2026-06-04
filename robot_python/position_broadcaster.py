#!/usr/bin/env python3
"""
Peer-to-peer UDP position broadcaster.

Runs two background threads:
  - Sender: pushes own position JSON to peer_ip:peer_port at broadcast_hz.
  - Listener: receives peer position from peer_port and stores it.

Usage:
  pb = PositionBroadcaster(peer_ip='192.168.1.x', role='car')
  pb.start()

  # In main loop, after position.process(frame):
  pb.set_own_position(pos_dict)       # pos_dict from PositionEstimator

  # In emergency handler:
  peer = pb.get_peer_position()       # returns dict or None
"""

import json
import logging
import socket
import threading
import time
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class PositionBroadcaster:

    def __init__(self,
                 peer_ip: str = '',
                 peer_port: int = 5002,
                 broadcast_hz: float = 10.0,
                 role: str = 'car'):

        self._peer_ip    = peer_ip
        self._peer_port  = peer_port
        self._interval   = 1.0 / max(broadcast_hz, 0.1)
        self._role       = role

        self._own_pos    = None             # dict from PositionEstimator
        self._peer_pos   = None             # dict received from peer
        self._peer_time  = 0.0             # monotonic time of last peer update
        self._lock       = threading.Lock()

        self._running    = False

    def start(self):
        if self._running:
            return
        self._running = True
        if not self._peer_ip:
            logger.warning("PositionBroadcaster: peer_ip not set — position sharing disabled")
            return
        threading.Thread(target=self._send_loop,   daemon=True, name='pos_sender').start()
        threading.Thread(target=self._listen_loop, daemon=True, name='pos_listener').start()
        logger.info("PositionBroadcaster started  peer=%s:%d  role=%s",
                    self._peer_ip, self._peer_port, self._role)

    def stop(self):
        self._running = False

    def set_own_position(self, pos: Optional[Dict]):
        with self._lock:
            self._own_pos = pos

    def get_peer_position(self) -> Optional[Dict]:
        with self._lock:
            return self._peer_pos

    def peer_position_age_s(self) -> float:
        """Seconds since last peer position update (large if never received)."""
        with self._lock:
            if self._peer_time == 0.0:
                return 9999.0
            return time.monotonic() - self._peer_time

    # ── Sender thread ────────────────────────────────────────────────────────
    def _send_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        while self._running:
            with self._lock:
                pos = self._own_pos

            if pos:
                try:
                    packet = json.dumps({
                        'type':       'POSITION',
                        'zone':       pos.get('zone', -1),
                        'distance_m': pos.get('distance_m', 0.0),
                        'role':       self._role,
                    }).encode('utf-8')
                    sock.sendto(packet, (self._peer_ip, self._peer_port))
                except Exception as e:
                    logger.error("Broadcast send error: %s", e)

            time.sleep(self._interval)
        sock.close()

    # ── Listener thread ──────────────────────────────────────────────────────
    def _listen_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)
        try:
            sock.bind(('0.0.0.0', self._peer_port))
        except OSError as e:
            logger.error("Cannot bind position listener on port %d: %s", self._peer_port, e)
            return

        while self._running:
            try:
                raw, _ = sock.recvfrom(512)
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    logger.error("Listener recv error: %s", e)
                continue

            try:
                msg = json.loads(raw.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

            if msg.get('type') != 'POSITION':
                continue
            if msg.get('role') == self._role:
                continue    # ignore own echo

            with self._lock:
                self._peer_pos  = {'zone': msg.get('zone', -1),
                                   'distance_m': msg.get('distance_m', 0.0)}
                self._peer_time = time.monotonic()

        sock.close()
