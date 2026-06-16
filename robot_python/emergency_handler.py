#!/usr/bin/env python3
"""
File: emergency_handler.py
Module: V2X Robot Platform — Emergency Vehicle Evasion State Machine

Purpose:
    Car-only state machine that intercepts lane_follower output and executes
    a five-state emergency evasion sequence when a V2X authenticated ambulance
    is detected behind the car:
        NORMAL → EVADING → HOLDING → RECOVERING → RESUMING → NORMAL
    In normal operation all commands pass through unmodified. Evasion is
    gated on both V2X authentication (Signal A) and known relative position
    via AprilTag UDP broadcast (Signal B).

Author(s): Praveen Kumar
Company: Siliris Technologies Pvt. Ltd
Created: 1st March 2026
Version: 1.0

State Summary:
    EVADING   — fixed veer toward evasion boundary (inner island default)
    HOLDING   — slow creep at boundary; exits when ambulance zone passes car
    RECOVERING — arc back to white line; falls back to timeout
    RESUMING  — ramp lane_follower output back up over ramp_duration_s

License:
    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
    Proprietary - See LICENSE file for terms and conditions.
"""

import logging
import math
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
                 position_timeout_s:      float = 3.0,
                 recovery_exit_mode:      str   = 'timer',
                 recovery_target_deg:     float = 30.0,
                 gyro_max_rad_s:          float = 4.0,
                 gyro_min_samples:        int   = 3):

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
        self._last_pos_log_t: float = 0.0   # rate-limit "waiting for position fix" log

        # Gyro-exit mode (recovery_exit_mode: gyro)
        self._rec_exit_mode        = recovery_exit_mode.lower()
        self._rec_target_rad       = math.radians(recovery_target_deg)
        self._gyro_max             = gyro_max_rad_s
        self._gyro_min_samples     = gyro_min_samples
        self._recovery_angle_rad   = 0.0   # accumulated rotation this RECOVERING arc
        self._recovery_gyro_samples = 0    # valid gyro readings this RECOVERING arc
        self._last_process_t       = 0.0   # for computing dt inside process()

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
                boundary_near: bool            = False,
                white_found:   bool            = False,
                yellow_cx:     Optional[float] = None,
                frame_w:       int             = 320,
                outer_tag:     bool            = False,
                gyro_z:        float           = 0.0) -> Tuple[float, float]:
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
        gyro_z        — yaw-rate from STM32 IMU in rad/s (positive = left turn).
                        Only used when recovery_exit_mode == 'gyro'. Safe to pass
                        even in timer mode — value is ignored.
        """
        self._last_vx = vx
        self._last_wz = wz

        now     = time.monotonic()
        elapsed = now - self._state_time

        # dt for gyro integration — computed before updating _last_process_t
        _gyro_dt = now - self._last_process_t
        self._last_process_t = now
        if _gyro_dt > 0.2 or _gyro_dt <= 0:
            _gyro_dt = 0.0   # reject first call and large gaps (stale / restart)

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
            # Both inner and outer evasion use boundary_near AND yellow_at_tgt.
            # boundary_near: yellow fills bottom half of ROI (large pixel count).
            # yellow_at_tgt: yellow centroid reached target x — fires BEFORE crossing,
            #                so the robot stops at the line instead of blowing through.
            # In daylight, yellow detection can be weaker → boundary_near alone fires
            # too late; yellow_at_tgt catches it earlier via the centroid position.
            yellow_at_tgt = (
                yellow_cx is not None and
                (yellow_cx / frame_w - self._ev_yellow_tgt) * self._dir * self._ev_side >= -0.05
            )
            if self._ev_side > 0:
                boundary_hit = past_min and (boundary_near or yellow_at_tgt)
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
            if self._ev_side > 0:
                # Inner evasion: range is entirely toward inner island.
                # max_ease = -0.05 (tiny left = minimum rightward approach speed).
                ev_wz = self._yellow_steer(yellow_cx, frame_w,
                                           max_toward=self._ev_angular,
                                           max_ease=-self._dir * self._ev_side * 0.05,
                                           bias=-self._dir * self._ev_side * 0.15,
                                           rescue_wz=self._dir * self._ev_side * 0.20)
            else:
                # Outer evasion: allow RIGHT turn when yellow reaches target.
                # Without this, max_ease=+0.05 (left) keeps robot pushing into boundary
                # even when yellow is at rel=0.30.  With right-capable max_ease and
                # slight right bias, robot decelerates approach BEFORE crossing the tape.
                ev_wz = self._yellow_steer(yellow_cx, frame_w,
                                           max_toward=self._ev_angular,
                                           max_ease=self._dir * self._ev_side * 0.08,
                                           bias=self._dir * self._ev_side * 0.05,
                                           rescue_wz=self._dir * self._ev_side * 0.20)
            return self._ev_linear, ev_wz

        # ── HOLDING ──────────────────────────────────────────────────────────
        elif self._state == _HOLDING:
            self._check_holding(now, elapsed)
            if self._ev_side > 0:
                # Inner evasion: slow creep against physical island wall.
                hold_vx = self._hold_vx
                hold_wz = self._yellow_steer(yellow_cx, frame_w,
                                             max_toward=-self._dir * self._ev_side * 0.25,
                                             max_ease=self._dir * self._ev_side * 0.05,
                                             bias=-self._dir * self._ev_side * 0.10,
                                             rescue_wz=self._dir * self._ev_side * 0.10)
            else:
                # Outer evasion: drive ALONG the outer yellow line (not hug — it's tape,
                # not a wall).  Right bias keeps the robot curving with the boundary;
                # yellow at rel≈0.30 (left) is the new guide like the white line.
                hold_vx = self._ev_linear   # normal evasion speed, not slow creep
                if yellow_cx is None:
                    # Yellow gone → ease right (likely drifted past tape or thin section)
                    hold_wz = self._dir * self._ev_side * 0.08   # CW outer: -0.08 (right)
                else:
                    # Yellow visible: proportional controller with right bias so robot
                    # naturally curves along the outer boundary.
                    hold_wz = self._yellow_steer(yellow_cx, frame_w,
                                                 max_toward=-self._dir * self._ev_side * 0.12,
                                                 max_ease=self._dir * self._ev_side * 0.08,
                                                 bias=self._dir * self._ev_side * 0.05,
                                                 rescue_wz=self._dir * self._ev_side * 0.05)
            return hold_vx, hold_wz

        # ── RECOVERING ───────────────────────────────────────────────────────
        elif self._state == _RECOVERING:
            # Accumulate rotation angle (gyro mode only)
            # Spike filter: IMU is inside aluminium chassis near motors — EMI spikes
            # can reach 10+ rad/s.  Reject anything above gyro_max_rad_s.
            # Also ignore tiny values (< 0.02 rad/s) which are sensor noise at rest.
            if self._rec_exit_mode == 'gyro' and _gyro_dt > 0:
                if 0.02 < abs(gyro_z) <= self._gyro_max:
                    self._recovery_angle_rad   += abs(gyro_z) * _gyro_dt
                    self._recovery_gyro_samples += 1

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
            elif (self._rec_exit_mode == 'gyro'
                  and self._recovery_gyro_samples >= self._gyro_min_samples
                  and self._recovery_angle_rad    >= self._rec_target_rad):
                logger.info("RECOVERING → RESUMING: gyro %.1f° reached (%d samples)",
                            math.degrees(self._recovery_angle_rad), self._recovery_gyro_samples)
                self._enter(_RESUMING, now)
            elif elapsed >= self._rec_dur:
                label = 'gyro fallback — timer fired' if self._rec_exit_mode == 'gyro' else 'timeout'
                logger.info("RECOVERING → RESUMING: %s (white not found)", label)
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
        if state == _RECOVERING:
            self._recovery_angle_rad    = 0.0
            self._recovery_gyro_samples = 0
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
        if self._force_yield:
            return True   # A button: bypass all position logic unconditionally
        if not self._position_known():
            now = time.monotonic()
            if now - self._last_pos_log_t >= 5.0:
                logger.info("Emergency active — waiting for position fix before yielding")
                self._last_pos_log_t = now
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
