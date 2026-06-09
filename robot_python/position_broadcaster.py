#!/usr/bin/env python3
"""
UDP position broadcaster — supports any number of cars and ambulances.

All robots broadcast their position to the subnet broadcast address.
Each robot listens on the same port and tracks all non-self peers.

Cars:       get_peer_position() returns the nearest ambulance position.
Ambulances: get_peer_position() returns the most recent car position.

Usage:
  pb = PositionBroadcaster(peer_ip='192.168.0.255', role='car')
  pb.start()
  pb.set_own_position(pos_dict)
  peer = pb.get_peer_position()    # dict or None
"""

import json
import logging
import socket
import threading
import time
from typing import Optional, Dict

logger = logging.getLogger(__name__)

_PEER_STALE_S = 5.0    # drop peer position after this many seconds without update


class PositionBroadcaster:

    def __init__(self,
                 peer_ip: str = '192.168.0.255',
                 peer_port: int = 5002,
                 broadcast_hz: float = 10.0,
                 role: str = 'car'):

        self._peer_ip   = peer_ip
        self._peer_port = peer_port
        self._interval  = 1.0 / max(broadcast_hz, 0.1)
        self._role      = role
        self._broadcast = peer_ip.endswith('.255') or peer_ip == '255.255.255.255'

        self._own_pos   = None
        # peer tracking: addr_str → {zone, distance_m, role, updated}
        self._peers: Dict[str, Dict] = {}
        self._lock      = threading.Lock()
        self._running   = False

    def start(self):
        if self._running:
            return
        self._running = True
        if not self._peer_ip:
            logger.warning("PositionBroadcaster: peer_ip not set — position sharing disabled")
            return
        threading.Thread(target=self._send_loop,   daemon=True, name='pos_sender').start()
        threading.Thread(target=self._listen_loop, daemon=True, name='pos_listener').start()
        mode = 'broadcast' if self._broadcast else 'unicast'
        logger.info("PositionBroadcaster started  %s=%s:%d  role=%s",
                    mode, self._peer_ip, self._peer_port, self._role)

    def stop(self):
        self._running = False

    def set_own_position(self, pos: Optional[Dict]):
        with self._lock:
            self._own_pos = pos

    def get_peer_position(self) -> Optional[Dict]:
        """
        Returns the best peer position:
          - Cars get the nearest ambulance (role='ambulance') that is not stale.
          - Ambulances get the most recently updated car (role='car').
        Returns None if no fresh peer exists.
        """
        now = time.monotonic()
        opposite = 'ambulance' if self._role == 'car' else 'car'

        with self._lock:
            candidates = [
                p for p in self._peers.values()
                if p['role'] == opposite and (now - p['updated']) < _PEER_STALE_S
            ]

        if not candidates:
            return None

        # For cars: pick ambulance with highest zone (furthest along = most likely behind)
        # For ambulances: pick most recently updated car
        if self._role == 'car':
            best = max(candidates, key=lambda p: p['zone'])
        else:
            best = max(candidates, key=lambda p: p['updated'])

        return {'zone': best['zone'], 'distance_m': best['distance_m']}

    def peer_position_age_s(self) -> float:
        """Seconds since the best peer last sent a position update."""
        now = time.monotonic()
        opposite = 'ambulance' if self._role == 'car' else 'car'
        with self._lock:
            times = [
                p['updated'] for p in self._peers.values()
                if p['role'] == opposite
            ]
        if not times:
            return 9999.0
        return now - max(times)

    # ── Sender ───────────────────────────────────────────────────────────────
    def _send_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if self._broadcast:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

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

    # ── Listener ─────────────────────────────────────────────────────────────
    def _listen_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if self._broadcast:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(1.0)
        try:
            sock.bind(('0.0.0.0', self._peer_port))
        except OSError as e:
            logger.error("Cannot bind position listener on port %d: %s", self._peer_port, e)
            return

        while self._running:
            try:
                raw, addr = sock.recvfrom(512)
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
            peer_role = msg.get('role', '')
            if peer_role == self._role:
                continue    # ignore same-role broadcasts (other cars / other ambulances)

            addr_key = addr[0]
            with self._lock:
                self._peers[addr_key] = {
                    'zone':       msg.get('zone', -1),
                    'distance_m': msg.get('distance_m', 0.0),
                    'role':       peer_role,
                    'updated':    time.monotonic(),
                }

        sock.close()
