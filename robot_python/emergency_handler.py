#!/usr/bin/env python3
"""
Emergency handler — car-only state machine.

Sits between lane_follower output and the robot driver.
In normal operation passes (vx, wz) straight through.
When an ambulance V2X emergency is active AND the ambulance is behind the
car, the handler drives a five-state evasion sequence:

  NORMAL → EVADING → HOLDING → RECOVERING → RESUMING → NORMAL

EVADING   : fixed veer toward the evasion boundary (inner island or outer edge,
            controlled by evasion_side config).  Default: inner (right turn CW).
HOLDING   : slow creep while hugging the evasion boundary
RECOVERING: arc back to white line.  Exits early if white line re-acquired and/or a
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
                 evasion_side:            str   = 'inner',
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
        d = +1 if driving_direction.lower().startswith('c') and 'counter' not in driving_direction.lower() else -1
        self._dir = d

        # Evasion side: +1 = inner (toward island), -1 = outer (toward boundary)
        # Multiplying ev/rec angular by (d * side) gives the correct sign in all cases.
        side = +1 if evasion_side.lower().startswith('i') else -1
        self._ev_side = side

        ev_mag  = abs(evasion_angular_speed)
        rec_mag = abs(recovery_angular_speed)

        self._ev_linear    = evasion_linear_speed
        self._ev_angular   = -d * side * ev_mag   # inner/CW: neg (right); outer/CW: pos (left)
        self._ev_dur       = evasion_duration_s
        self._ev_min       = min_evasion_s
        self._ev_yellow_kp = evasion_yellow_kp
        # Target fraction: user specifies inner-CW value (0.70 = right side of frame).
        # inner/CW: 0.50 + 1*0.20 = 0.70   outer/CW: 0.50 - 1*0.20 = 0.30
        self._ev_yellow_tgt = 0.50 + d * side * abs(evasion_yellow_target - 0.50)
        self._hold_vx      = hold_linear_speed
        self._rec_linear   = recovery_linear_speed
        self._rec_angular  = d * side * rec_mag   # inner/CW: pos (left back); outer/CW: neg (right back)
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
        self._force_yield  = False   # bypass position check (solo-car test via A button)

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

    def set_force_yield(self, val: bool):
        """
        True  → skip position check; yield immediately when emergency is active.
               Use for solo-car testing (A button, no ambulance broadcasting).
        False → normal position-based logic resumes.
               Safe to call when real V2X is active — bridge keeps emergency True
               so the ambulance signal is never dropped.
        """
        self._force_yield = val
        if val:
            logger.info("Force-yield ON — position check bypassed")
        else:
            logger.info("Force-yield OFF — position check active")

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
                frame_w:       int           = 320,
                outer_tag:     bool          = False) -> Tuple[float, float]:
        """
        Call at ~20 Hz.  Returns (vx, wz) to send to robot driver.

        boundary_near — True when camera sees yellow tape close ahead (inner island);
                        triggers HOLDING (but only after min_evasion_s in EVADING).
        white_found   — True when the lane follower has re-acquired the white line;
                        used by RECOVERING to exit early.
        yellow_cx     — pixel X of yellow centroid in the camera frame (None if not seen);
                        used for proportional steering during EVADING and HOLDING.
        frame_w       — camera frame width in pixels (default 320).
        outer_tag     — True when an outer boundary AprilTag (IDs 10-17) was detected.
                        Inner evasion RECOVERING: robot overshot the white line — stop arc.
                        Outer evasion EVADING: robot has reached the outer boundary — start HOLDING.
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
            past_min = elapsed >= self._ev_min
            # Primary trigger: yellow fills bottom half of ROI (wide inner island).
            # Secondary triggers for outer evasion (outer tape is thin — bottom-half
            # detection fires too late):
            #   yellow_at_tgt: yellow centroid has reached target x-position, meaning
            #                  the robot is AT the boundary before crossing it.
            #   outer_tag:     outer boundary AprilTag visible — belt-and-suspenders.
            yellow_at_tgt = (
                yellow_cx is not None and
                (yellow_cx / frame_w - self._ev_yellow_tgt) * self._dir * self._ev_side >= -0.05
            )
            if self._ev_side > 0:
                boundary_hit = past_min and boundary_near
            else:
                boundary_hit = past_min and (boundary_near or outer_tag or yellow_at_tgt)
            if boundary_hit:
                logger.info("EVADING → HOLDING: boundary reached "
                            "(boundary_near=%s outer_tag=%s yellow_at_tgt=%s, %.1fs)",
                            boundary_near, outer_tag, yellow_at_tgt, elapsed)
                self._enter(_HOLDING, now)
            elif elapsed >= self._ev_dur:
                logger.info("EVADING → HOLDING: evasion timer expired")
                self._enter(_HOLDING, now)
            ev_wz = self._yellow_steer(yellow_cx, frame_w,
                                       max_toward=self._ev_angular,
                                       max_ease=-self._dir * self._ev_side * 0.05,
                                       bias=-self._dir * self._ev_side * 0.15,
                                       rescue_wz=self._dir * self._ev_side * 0.20)
            return self._ev_linear, ev_wz

        # ── HOLDING ──────────────────────────────────────────────────────────
        elif self._state == _HOLDING:
            self._check_holding(now, elapsed)
            # Yellow tracking holds robot against evasion boundary.
            # ev_side flips all signs: inner uses inner island yellow, outer uses outer tape.
            # For outer CW: max_ease = d*side*0.05 = -0.05 → allows tiny right turn
            # when robot is too close to boundary, preventing overshoot in HOLDING.
            hold_wz = self._yellow_steer(yellow_cx, frame_w,
                                         max_toward=-self._dir * self._ev_side * 0.25,
                                         max_ease=self._dir * self._ev_side * 0.05,
                                         bias=-self._dir * self._ev_side * 0.10,
                                         rescue_wz=self._dir * self._ev_side * 0.10)
            return self._hold_vx, hold_wz

        # ── RECOVERING ───────────────────────────────────────────────────────
        elif self._state == _RECOVERING:
            # Tag seen during recovery = robot has a position fix near the oval
            tag_seen = (self._own_zone_t > self._state_time + 0.3)

            if outer_tag and self._ev_side > 0:
                # Inner evasion only: outer tag means robot overshot the white line
                # during outward arc.  Stop now.
                # (Outer evasion RECOVERING starts at the outer boundary — outer_tag
                # fires immediately and must be ignored here.)
                logger.warning("RECOVERING → RESUMING: outer tag seen — overshot white line")
                self._enter(_RESUMING, now)
            elif white_found:
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
        if (rel - 0.50) * self._dir * self._ev_side < -0.05:
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
        if self._force_yield and not self._position_known():
            return True   # solo test: A button pressed, no ambulance broadcasting
        if not self._position_known():
            logger.info("Emergency active — waiting for position fix before yielding")
            return False
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
