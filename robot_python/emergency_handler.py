#!/usr/bin/env python3
"""
Emergency handler — car-only state machine.

Sits between lane_follower output and the robot driver.
In normal operation passes (vx, wz) straight through.
When an ambulance V2X emergency is active AND the ambulance is behind the
car, the handler drives a five-state evasion sequence:

  NORMAL → EVADING → HOLDING → RECOVERING → RESUMING → NORMAL

EVADING   : fixed veer toward inner island (right turn, negative wz)
HOLDING   : stationary wait while ambulance passes
RECOVERING: fixed outward drive (left turn, positive wz) to get back to
            white line.  Exits early if white line re-acquired and/or a
            tag is detected (robot has a position fix near the oval).
            Falls back to timeout if line is never found.
RESUMING  : ramp follower output back up from zero over ramp_duration_s

Usage:
  eh = EmergencyHandler(cfg)
  eh.update_own_position(pos_dict)       # called after position.process()
  eh.update_peer_position(pos_dict)      # called after broadcaster.get_peer_position()
  eh.update_emergency(True/False)        # called after v2x_bridge.is_emergency()

  vx, wz = eh.process(vx_line, wz_line,
                       boundary_near=False,
                       white_found=False)
"""

import logging
import time
from typing import Optional, Tuple, Dict

logger = logging.getLogger(__name__)

_NORMAL     = 'NORMAL'
_EVADING    = 'EVADING'
_HOLDING    = 'HOLDING'
_RECOVERING = 'RECOVERING'
_RESUMING   = 'RESUMING'


class EmergencyHandler:

    def __init__(self,
                 driving_direction:       str   = 'clockwise',
                 evasion_linear_speed:    float = 0.06,
                 evasion_angular_speed:   float = 0.35,
                 evasion_duration_s:      float = 6.0,
                 min_evasion_s:           float = 0.2,
                 evasion_yellow_target:   float = 0.70,
                 evasion_yellow_kp:       float = 2.5,
                 hold_linear_speed:       float = 0.04,
                 recovery_linear_speed:   float = 0.08,
                 recovery_angular_speed:  float = 0.45,
                 recovery_duration_s:     float = 2.5,
                 hold_timeout_s:          float = 30.0,
                 clear_delay_s:           float = 1.0,
                 resume_ramp_duration_s:  float = 2.0,
                 n_tags:                  int   = 10,
                 yield_zone_gap:          int   = 3,
                 position_timeout_s:      float = 3.0):

        # Direction sign: +1 = clockwise (inner island to RIGHT of robot)
        #                 -1 = counterclockwise (inner island to LEFT of robot)
        # All angular speeds are stored as magnitudes in config; _dir applies the sign.
        # "toward inner island" = -_dir   "toward outer lane (white)" = +_dir
        d = +1 if driving_direction.lower().startswith('c') and 'counter' not in driving_direction.lower() else -1
        self._dir = d

        ev_mag  = abs(evasion_angular_speed)
        rec_mag = abs(recovery_angular_speed)

        self._ev_linear    = evasion_linear_speed
        self._ev_angular   = -d * ev_mag          # toward inner island (CW: neg, CCW: pos)
        self._ev_dur       = evasion_duration_s
        self._ev_min       = min_evasion_s
        self._ev_yellow_kp = evasion_yellow_kp
        # Target fraction of frame where yellow should appear.
        # User always specifies the clockwise value (0.70 = right side).
        # For CCW the inner island is on the LEFT, so we mirror around 0.5.
        self._ev_yellow_tgt = 0.50 + d * abs(evasion_yellow_target - 0.50)
        self._hold_vx      = hold_linear_speed
        self._rec_linear   = recovery_linear_speed
        self._rec_angular  = d * rec_mag           # toward outer lane (CW: pos, CCW: neg)
        self._rec_dur      = recovery_duration_s
        self._hold_max     = hold_timeout_s
        self._clear_delay  = clear_delay_s
        self._ramp_dur     = resume_ramp_duration_s
        self._n_tags       = n_tags
        self._yield_gap    = yield_zone_gap
        self._pos_timeout  = position_timeout_s

        # State machine
        self._state        = _NORMAL
        self._state_time   = time.monotonic()

        # Emergency flag
        self._emergency    = False
        self._was_active   = False

        # Last line-follower command (for pass-through and ramp)
        self._last_vx      = 0.0
        self._last_wz      = 0.0

        # Position
        self._own_zone     = -1
        self._own_zone_t   = 0.0   # monotonic time of last zone update
        self._amb_zone     = -1
        self._amb_time     = 0.0

        # Holding timers
        self._passed_stamp = None
        self._clear_stamp  = None

    # ── Input setters ────────────────────────────────────────────────────────
    def update_own_position(self, pos: Optional[Dict]):
        if pos:
            self._own_zone   = int(pos.get('zone', -1))
            self._own_zone_t = time.monotonic()

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
        self._emergency  = active
        self._was_active = active

    def get_state(self) -> str:
        return self._state

    # ── Main tick ────────────────────────────────────────────────────────────
    def process(self, vx: float, wz: float,
                boundary_near: bool          = False,
                white_found:   bool          = False,
                yellow_cx:     Optional[float] = None,
                frame_w:       int           = 320) -> Tuple[float, float]:
        """
        Call at ~20 Hz.  Returns (vx, wz) to send to robot driver.

        boundary_near — True when camera sees yellow tape close ahead (inner island);
                        triggers HOLDING (but only after min_evasion_s in EVADING).
        white_found   — True when the lane follower has re-acquired the white line;
                        used by RECOVERING to exit early.
        yellow_cx     — pixel X of yellow centroid in the camera frame (None if not seen);
                        used for proportional steering during EVADING and HOLDING.
        frame_w       — camera frame width in pixels (default 320).
        """
        self._last_vx = vx
        self._last_wz = wz

        now     = time.monotonic()
        elapsed = now - self._state_time

        # ── NORMAL ──────────────────────────────────────────────────────────
        if self._state == _NORMAL:
            if self._should_yield():
                logger.warning("YIELDING — amb=%d  own=%d  gap=%d zones",
                               self._amb_zone, self._own_zone, self._amb_gap())
                self._enter(_EVADING, now)
            return vx, wz

        # ── EVADING ─────────────────────────────────────────────────────────
        elif self._state == _EVADING:
            # Respect min_evasion_s so boundary_near can't skip before we move
            past_min = elapsed >= self._ev_min
            if past_min and boundary_near:
                logger.info("EVADING → HOLDING: inner boundary detected (%.1fs elapsed)", elapsed)
                self._enter(_HOLDING, now)
            elif elapsed >= self._ev_dur:
                logger.info("EVADING → HOLDING: evasion timer expired")
                self._enter(_HOLDING, now)
            # Yellow-guided steering: proportional control to bring yellow to right edge.
            # No yellow visible → hard right (ev_angular). Yellow visible → ease off as
            # robot approaches inner island. Never turns LEFT during evasion (max_left=-0.05).
            ev_wz = self._yellow_steer(yellow_cx, frame_w,
                                       max_toward=self._ev_angular,
                                       max_ease=-self._dir * 0.05,
                                       bias=-self._dir * 0.15,
                                       rescue_wz=self._dir * 0.20)
            return self._ev_linear, ev_wz

        # ── HOLDING ──────────────────────────────────────────────────────────
        elif self._state == _HOLDING:
            self._check_holding(now, elapsed)
            # Slow creep while hugging inner yellow — keeps robot moving with traffic
            # and maintains position against the island rather than sitting in the lane.
            hold_wz = self._yellow_steer(yellow_cx, frame_w,
                                         max_toward=-self._dir * 0.25,
                                         max_ease=self._dir * 0.05,
                                         bias=-self._dir * 0.10,
                                         rescue_wz=self._dir * 0.10)
            return self._hold_vx, hold_wz

        # ── RECOVERING ───────────────────────────────────────────────────────
        elif self._state == _RECOVERING:
            # Tag seen during recovery = robot has a position fix near the oval
            tag_seen = (self._own_zone_t > self._state_time + 0.3)

            if white_found:
                logger.info("RECOVERING → RESUMING: white line re-acquired"
                            + (" (tag z=%d)" % self._own_zone if tag_seen else ""))
                self._enter(_RESUMING, now)
            elif elapsed >= self._rec_dur:
                logger.info("RECOVERING → RESUMING: timeout (white not found)")
                self._enter(_RESUMING, now)
            return self._rec_linear, self._rec_angular

        # ── RESUMING ─────────────────────────────────────────────────────────
        elif self._state == _RESUMING:
            ramp = min(elapsed / max(self._ramp_dur, 0.1), 1.0)
            if elapsed >= self._ramp_dur:
                self._enter(_NORMAL, now)
                logger.info("Resumed normal lane following")
            return vx * ramp, wz * ramp

        return vx, wz

    # ── State helpers ────────────────────────────────────────────────────────
    def _yellow_steer(self, yellow_cx: Optional[float], frame_w: int,
                      max_toward: float, max_ease: float, bias: float,
                      rescue_wz: float) -> float:
        """
        Proportional yellow-tracking controller — direction-agnostic.

          max_toward — hardest turn toward inner island (CW: -0.35, CCW: +0.35)
          max_ease   — softest toward-inner limit    (CW: -0.05, CCW: +0.05)
          bias       — equilibrium wz when yellow is exactly at target
                       (CW: -0.15 = gentle right,  CCW: +0.15 = gentle left)
          rescue_wz  — wz when robot has overshot and yellow is on wrong side
                       (CW: +0.20 = turn left out, CCW: -0.20 = turn right out)

        Overshoot detection: yellow crossed centre to the side OPPOSITE the inner island.
        For CW that is rel < 0.45 (yellow on left).
        For CCW that is rel > 0.55 (yellow on right).
        Unified: (rel - 0.50) * _dir < -0.05
        """
        if yellow_cx is None:
            return max_toward   # no yellow visible: turn hard toward inner island
        rel = yellow_cx / frame_w
        if (rel - 0.50) * self._dir < -0.05:
            # Yellow is on the wrong side — robot overshot the inner island line.
            return rescue_wz
        err = rel - self._ev_yellow_tgt   # positive = yellow further toward inner island
        wz  = self._ev_yellow_kp * err + bias
        # Clamp between the two limits (works regardless of their sign order)
        lo, hi = min(max_toward, max_ease), max(max_toward, max_ease)
        return max(lo, min(hi, wz))

    def _enter(self, state: str, now: float):
        self._state      = state
        self._state_time = now
        if state == _HOLDING:
            self._passed_stamp = None
            self._clear_stamp  = None
        logger.info("Emergency handler → %s", state)

    def _check_holding(self, now: float, elapsed: float):
        """Decide when HOLDING → RECOVERING."""
        if self._position_known():
            if not self._is_amb_behind():
                if self._passed_stamp is None:
                    self._passed_stamp = now
                    logger.info("Ambulance overtook car — grace period starting")
                elif (now - self._passed_stamp) >= self._clear_delay:
                    self._enter(_RECOVERING, now)
            else:
                self._passed_stamp = None
        elif not self._emergency:
            if self._clear_stamp is None:
                self._clear_stamp = now
            elif (now - self._clear_stamp) >= self._clear_delay:
                self._enter(_RECOVERING, now)
        else:
            self._clear_stamp = None

        if elapsed >= self._hold_max:
            logger.warning("Hold timeout — auto-recovering")
            self._enter(_RECOVERING, now)

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
