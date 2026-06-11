#!/usr/bin/env python3
"""
Emergency handler — car-only state machine.

Sits between lane_follower output and the robot driver.
In normal operation passes (vx, wz) straight through.
When an ambulance V2X emergency is active AND the ambulance is behind the
car, the handler drives a four-state evasion sequence:

  NORMAL → EVADING → HOLDING → RESUMING → NORMAL

Indian-road convention: ambulance approaches from behind → car steers LEFT.
Positive wz = counter-clockwise = left turn.

Usage:
  eh = EmergencyHandler(cfg)
  eh.update_own_position(pos_dict)       # called after position.process()
  eh.update_peer_position(pos_dict)      # called after broadcaster.get_peer_position()
  eh.update_emergency(True/False)        # called after v2x_bridge.is_emergency()

  vx, wz = eh.process(vx_line, wz_line) # call at ~20 Hz in main loop
"""

import logging
import time
from typing import Optional, Tuple, Dict

logger = logging.getLogger(__name__)

_NORMAL   = 'NORMAL'
_EVADING  = 'EVADING'
_HOLDING  = 'HOLDING'
_RESUMING = 'RESUMING'


class EmergencyHandler:

    def __init__(self,
                 evasion_linear_speed:   float = 0.12,
                 evasion_angular_speed:  float = 0.9,
                 evasion_duration_s:     float = 2.0,
                 hold_timeout_s:         float = 30.0,
                 clear_delay_s:          float = 1.0,
                 resume_ramp_duration_s: float = 2.0,
                 n_tags:                 int   = 10,
                 yield_zone_gap:         int   = 4,
                 position_timeout_s:     float = 3.0):

        self._ev_linear   = evasion_linear_speed
        self._ev_angular  = evasion_angular_speed
        self._ev_dur      = evasion_duration_s
        self._hold_max    = hold_timeout_s
        self._clear_delay = clear_delay_s
        self._ramp_dur    = resume_ramp_duration_s
        self._n_tags      = n_tags
        self._yield_gap   = yield_zone_gap
        self._pos_timeout = position_timeout_s

        # State machine
        self._state       = _NORMAL
        self._state_time  = time.monotonic()

        # Emergency flag
        self._emergency   = False
        self._was_active  = False          # edge detect for log

        # Last line-follower command (for pass-through and ramp)
        self._last_vx     = 0.0
        self._last_wz     = 0.0

        # Position
        self._own_zone    = -1
        self._amb_zone    = -1
        self._amb_time    = 0.0

        # Holding timers
        self._passed_stamp = None
        self._clear_stamp  = None

    # ── Input setters ────────────────────────────────────────────────────────
    def update_own_position(self, pos: Optional[Dict]):
        if pos:
            self._own_zone = int(pos.get('zone', -1))

    def update_peer_position(self, pos: Optional[Dict]):
        if pos:
            self._amb_zone = int(pos.get('zone', -1))
            self._amb_time = time.monotonic()

    def update_emergency(self, active: bool):
        if active and not self._was_active:
            logger.warning("V2X emergency ACTIVE  own=%d  amb=%d",
                           self._own_zone, self._amb_zone)
        elif not active and self._was_active:
            self._clear_stamp = time.monotonic()
            logger.info("V2X emergency CLEARED")
        self._emergency   = active
        self._was_active  = active

    def get_state(self) -> str:
        return self._state

    # ── Main tick ────────────────────────────────────────────────────────────
    def process(self, vx: float, wz: float) -> Tuple[float, float]:
        """
        Call at ~20 Hz.  Returns (vx, wz) to send to robot driver.
        """
        self._last_vx = vx
        self._last_wz = wz

        now     = time.monotonic()
        elapsed = now - self._state_time

        if self._state == _NORMAL:
            if self._should_yield():
                logger.warning("YIELDING — amb=%d  own=%d  gap=%d zones",
                               self._amb_zone, self._own_zone, self._amb_gap())
                self._enter(_EVADING, now)
            return vx, wz

        elif self._state == _EVADING:
            if elapsed >= self._ev_dur:
                self._enter(_HOLDING, now)
            return self._ev_linear, self._ev_angular

        elif self._state == _HOLDING:
            self._check_holding(now, elapsed)
            return 0.0, 0.0

        elif self._state == _RESUMING:
            ramp = min(elapsed / max(self._ramp_dur, 0.1), 1.0)
            if elapsed >= self._ramp_dur:
                self._enter(_NORMAL, now)
                logger.info("Resumed normal lane following")
            return vx * ramp, wz * ramp

        return vx, wz

    # ── State helpers ────────────────────────────────────────────────────────
    def _enter(self, state: str, now: float):
        self._state      = state
        self._state_time = now
        if state == _HOLDING:
            self._passed_stamp = None
            self._clear_stamp  = None
        logger.info("Emergency handler → %s", state)

    def _check_holding(self, now: float, elapsed: float):
        if self._position_known():
            if not self._is_amb_behind():
                if self._passed_stamp is None:
                    self._passed_stamp = now
                    logger.info("Ambulance overtook car — grace period starting")
                elif (now - self._passed_stamp) >= self._clear_delay:
                    self._enter(_RESUMING, now)
            else:
                self._passed_stamp = None
        elif not self._emergency:
            if self._clear_stamp is None:
                self._clear_stamp = now
            elif (now - self._clear_stamp) >= self._clear_delay:
                self._enter(_RESUMING, now)
        else:
            self._clear_stamp = None

        if elapsed >= self._hold_max:
            logger.warning("Hold timeout — auto-resuming")
            self._enter(_RESUMING, now)

    # ── Position logic ───────────────────────────────────────────────────────
    def _position_known(self) -> bool:
        age = time.monotonic() - self._amb_time
        return (self._own_zone >= 0 and self._amb_zone >= 0 and age < self._pos_timeout)

    def _is_amb_behind(self) -> bool:
        diff = (self._own_zone - self._amb_zone) % self._n_tags
        return 0 < diff <= (self._n_tags // 2)

    def _amb_gap(self) -> int:
        diff = (self._own_zone - self._amb_zone) % self._n_tags
        return min(diff, self._n_tags - diff)

    def _should_yield(self) -> bool:
        if not self._emergency:
            return False
        if not self._position_known():
            logger.warning("Position unknown — yielding on V2X signal alone (fallback)")
            return True
        behind = self._is_amb_behind()
        gap    = self._amb_gap()
        if behind and gap <= self._yield_gap:
            return True
        if not behind:
            logger.info("Ambulance AHEAD (amb=%d car=%d) — NOT yielding",
                        self._amb_zone, self._own_zone)
        elif gap > self._yield_gap:
            logger.info("Ambulance %d zones behind (> %d gap) — not yielding yet",
                        gap, self._yield_gap)
        return False
