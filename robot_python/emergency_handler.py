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
                 evade_watchdog_s:        float = 5.0,
                 clear_delay_s:           float = 1.0,
                 resume_ramp_duration_s:  float = 2.0,
                 n_tags:                  int   = 10,
                 yield_zone_gap:          int   = 3,
                 recover_min_gap:         int   = 1,
                 position_timeout_s:      float = 3.0,
                 recovery_exit_mode:      str   = 'timer',
                 recovery_target_deg:     float = 30.0,
                 gyro_max_rad_s:          float = 4.0,
                 gyro_min_samples:        int   = 3,
                 # ── Outer-evasion follow tuning (evasion_side: outer) ──
                 outer_perp_cy:           float = 0.45,
                 outer_perp_turn:         float = 0.30,
                 outer_centre_guard:      float = 0.10,
                 outer_centre_turn:       float = 0.40,
                 outer_follow_kp:         float = 2.5,
                 outer_max_away:          float = 0.40,
                 outer_established_tol:   float = 0.10,
                 cross_guard_vx:          float = 0.02,
                 # ── RECOVERING white-seek + RESUMING tuning ──
                 rec_white_kp:            float = 0.006,
                 rec_white_max:           float = 0.60,
                 rec_white_tol:           float = 40.0,
                 resume_vx_floor:         float = 0.50):

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
        self._evade_watchdog = evade_watchdog_s
        self._clear_delay  = clear_delay_s
        self._ramp_dur     = resume_ramp_duration_s
        self._n_tags       = n_tags
        self._yield_gap    = yield_zone_gap
        self._recover_min_gap = recover_min_gap
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
        self._hold_min_gap = 999   # closest the ambulance got during this HOLD

        # Outer-evasion boundary lock: True once yellow has been seen this episode.
        # Stops the "no yellow → arc toward boundary" branch from steering the car
        # back across the line if the detector blinks after it has locked on.
        self._outer_yellow_seen = False

        # Watchdog: monotonic time the current evasion episode (EVADING) started.
        self._evade_start_t = 0.0
        self._last_pos_log_t: float = 0.0   # rate-limit "waiting for position fix" log

        # Gyro-exit mode (recovery_exit_mode: gyro)
        self._rec_exit_mode        = recovery_exit_mode.lower()
        self._rec_target_rad       = math.radians(recovery_target_deg)
        self._gyro_max             = gyro_max_rad_s
        self._gyro_min_samples     = gyro_min_samples
        self._recovery_angle_rad   = 0.0   # accumulated rotation this RECOVERING arc
        self._recovery_gyro_samples = 0    # valid gyro readings this RECOVERING arc
        self._last_process_t       = 0.0   # for computing dt inside process()

        # Outer-evasion follow tuning (see _outer_steer)
        self._outer_perp_cy        = float(outer_perp_cy)
        self._outer_perp_turn      = abs(float(outer_perp_turn))
        self._outer_centre_guard   = float(outer_centre_guard)
        self._outer_centre_turn    = abs(float(outer_centre_turn))
        self._outer_follow_kp      = float(outer_follow_kp)
        self._outer_max_away       = abs(float(outer_max_away))
        self._outer_est_tol        = float(outer_established_tol)
        self._cross_guard_vx       = abs(float(cross_guard_vx))

        # RECOVERING white-seek + RESUMING tuning
        self._rec_white_kp         = float(rec_white_kp)
        self._rec_white_max        = abs(float(rec_white_max))
        self._rec_white_tol        = abs(float(rec_white_tol))
        self._resume_vx_floor      = float(max(0.0, min(1.0, resume_vx_floor)))

    # ── Input setters ────────────────────────────────────────────────────────
    def update_own_position(self, pos: Optional[Dict]):
        if pos:
            self._own_zone   = int(pos.get('zone', -1))
            self._own_zone_t = time.monotonic()

    def update_peer_position(self, pos: Optional[Dict]):
        if pos:
            self._amb_zone = int(pos.get('zone', -1))
            self._amb_time = time.monotonic()

    def cancel_sim(self):
        """
        B button (ambulance departed): clear the sim emergency and recover.

        Previously this snapped straight to NORMAL, which dumped the robot out
        at the boundary onto the raw lane follower (it then drove straight /
        almost out of the arena instead of coming back in).  Now, if we are
        mid-evasion, it kicks off the proper RECOVERING → RESUMING → NORMAL
        sequence so the robot steers back to the white line in a controlled arc.
        """
        self._emergency  = False
        self._was_active = False
        if self._state in (_EVADING, _HOLDING):
            logger.info("B button: ambulance departed → RECOVERING")
            self._enter(_RECOVERING, time.monotonic())
        # RECOVERING / RESUMING already heading home; NORMAL has nothing to do.

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

    def get_yield_status(self) -> dict:
        """Returns info for the stream overlay — zones, direction, force flag."""
        known   = self._position_known()
        behind  = self._is_amb_behind() if known else None
        gap     = self._amb_gap()        if known else None
        return {
            'force_yield': self._force_yield,
            'amb_known':   known,
            'amb_behind':  behind,
            'amb_gap':     gap,
        }

    # ── Main tick ────────────────────────────────────────────────────────────
    def process(self, vx: float, wz: float,
                boundary_near:  bool            = False,
                white_found:    bool            = False,
                yellow_cx:      Optional[float] = None,
                yellow_cy_frac: Optional[float] = None,
                frame_w:        int             = 320,
                outer_tag:      bool            = False,
                gyro_z:         float           = 0.0,
                white_err:      Optional[float] = None) -> Tuple[float, float]:
        """
        Call at ~20 Hz.  Returns (vx, wz) to send to robot driver.

        boundary_near   — True when yellow tape is dense in the bottom quarter of the ROI;
                          triggers HOLDING (only after min_evasion_s in EVADING).
        white_found     — True when the lane follower has re-acquired the white line.
        yellow_cx       — pixel X of yellow at the Pure Pursuit lookahead distance (None if
                          not seen). Used for proportional steering in EVADING phase 2 and HOLDING.
        yellow_cy_frac  — normalised vertical centroid of the yellow blob: 0.0 = top of ROI
                          (yellow is far ahead, robot approaching tape perpendicularly),
                          1.0 = bottom (yellow is close alongside the robot).
                          Used to distinguish "yellow at top → turn left to align" from
                          "yellow on right → follow it".
        frame_w         — camera frame width in pixels (default 320).
        outer_tag       — True when an outer boundary AprilTag was detected.
        gyro_z          — yaw-rate from STM32 IMU in rad/s (positive = left turn).
        white_err       — signed lateral offset of the white line from the lane target
                          in pixels (positive = white right of centre). Used during
                          RECOVERING to actively steer back onto the white line.
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
            if self._watchdog_tripped(now):
                logger.warning("Evade watchdog: %.1fs off white with no fresh "
                               "ambulance data — recovering to white",
                               now - self._evade_start_t)
                self._enter(_RECOVERING, now)
                return self._rec_linear, self._rec_angular
            past_min = elapsed >= self._ev_min

            if self._ev_side > 0:
                # ===== INNER evasion (toward inner island) — unchanged =====
                # Rely only on boundary_near (yellow DENSE in bottom quarter of ROI,
                # meaning the robot is physically at the inner island tape) + timer.
                boundary_hit = past_min and boundary_near
                if boundary_hit:
                    logger.info("EVADING → HOLDING: inner boundary reached "
                                "(boundary_near=%s, %.1fs)", boundary_near, elapsed)
                    self._enter(_HOLDING, now)
                elif elapsed >= self._ev_dur:
                    logger.info("EVADING → HOLDING: evasion timer expired")
                    self._enter(_HOLDING, now)

                # Inner evasion — two-phase:
                # Phase 1 (elapsed < ev_min): blind open-loop turn toward inner island.
                # Phase 2 (elapsed >= ev_min): alignment using yellow vertical position.
                if elapsed < self._ev_min:
                    ev_wz = self._ev_angular   # Phase 1: blind right turn, no sensing
                elif yellow_cx is None or yellow_cy_frac is None:
                    ev_wz = self._ev_angular   # no yellow detected: keep going right
                elif yellow_cy_frac < 0.45:
                    # Yellow at top of frame = approaching tape perpendicularly.
                    # Turn LEFT so tape swings from "ahead" into the right side.
                    ev_wz = self._dir * self._ev_side * 0.20   # CW inner: +0.20 (left)
                else:
                    ev_wz = self._yellow_steer(yellow_cx, frame_w,
                                               max_toward=self._ev_angular,
                                               max_ease=-self._dir * self._ev_side * 0.05,
                                               bias=-self._dir * self._ev_side * 0.15,
                                               rescue_wz=self._dir * self._ev_side * 0.20)
                return self._ev_linear, ev_wz

            # ===== OUTER evasion (toward outer boundary) =====
            # Steer toward the outer boundary and follow it (see _outer_steer).
            # EVADING → HOLDING once the robot is established parallel to the
            # boundary with yellow held on the evasion side, OR via the dense
            # boundary / outer-AprilTag / timer fallbacks.
            ev_vx, ev_wz, established = self._outer_steer(
                yellow_cx, yellow_cy_frac, frame_w, self._ev_linear,
                boundary_near=boundary_near)
            if past_min and (established or boundary_near or outer_tag):
                logger.info("EVADING → HOLDING: outer boundary reached "
                            "(established=%s boundary_near=%s outer_tag=%s, %.1fs)",
                            established, boundary_near, outer_tag, elapsed)
                self._enter(_HOLDING, now)
            elif elapsed >= self._ev_dur:
                logger.info("EVADING → HOLDING: evasion timer expired")
                self._enter(_HOLDING, now)
            return ev_vx, ev_wz

        # ── HOLDING ──────────────────────────────────────────────────────────
        elif self._state == _HOLDING:
            if self._watchdog_tripped(now):
                logger.warning("Evade watchdog: %.1fs off white with no fresh "
                               "ambulance data — recovering to white",
                               now - self._evade_start_t)
                self._enter(_RECOVERING, now)
                return self._rec_linear, self._rec_angular
            self._check_holding(now, elapsed)
            if self._ev_side > 0:
                # Inner evasion: slow creep alongside the island tape.
                hold_vx = self._hold_vx
                if yellow_cy_frac is not None and yellow_cy_frac < 0.40:
                    # Yellow still at top = not yet parallel (entered HOLDING early via timer).
                    # Continue left turn to finish alignment before starting to follow.
                    hold_wz = self._dir * self._ev_side * 0.15   # CW inner: +0.15 (left)
                else:
                    hold_wz = self._yellow_steer(yellow_cx, frame_w,
                                                 max_toward=-self._dir * self._ev_side * 0.25,
                                                 max_ease=self._dir * self._ev_side * 0.05,
                                                 bias=-self._dir * self._ev_side * 0.10,
                                                 rescue_wz=self._dir * self._ev_side * 0.10)
                return hold_vx, hold_wz

            # Outer evasion: keep driving ALONG the outer yellow boundary (yellow
            # held on the evasion side, never centred, never crossed) while the
            # ambulance passes.  Same controller as the EVADING approach.
            hold_vx, hold_wz, _ = self._outer_steer(
                yellow_cx, yellow_cy_frac, frame_w, self._ev_linear,
                boundary_near=boundary_near)
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

            # White is "re-acquired enough to hand back" only once it is roughly
            # centred — not on the first edge-of-frame glimpse.  This keeps the
            # robot driving toward the line in one motion instead of stalling and
            # nudging little by little (and sometimes losing it).
            white_centered = (white_found and white_err is not None
                              and abs(white_err) <= self._rec_white_tol)

            if outer_tag and self._ev_side > 0:
                # Inner evasion only: outer tag means robot overshot the white line
                # during outward arc.  Stop now.
                logger.warning("RECOVERING → RESUMING: outer tag seen — overshot white line")
                self._enter(_RESUMING, now)
            elif white_centered:
                logger.info("RECOVERING → RESUMING: white line centred (err=%s)", white_err)
                self._enter(_RESUMING, now)
            elif (self._rec_exit_mode == 'gyro'
                  and not white_found
                  and self._recovery_gyro_samples >= self._gyro_min_samples
                  and self._recovery_angle_rad    >= self._rec_target_rad):
                logger.info("RECOVERING → RESUMING: gyro %.1f° reached (%d samples)",
                            math.degrees(self._recovery_angle_rad), self._recovery_gyro_samples)
                self._enter(_RESUMING, now)
            elif elapsed >= self._rec_dur:
                logger.info("RECOVERING → RESUMING: timeout (white not centred)")
                self._enter(_RESUMING, now)

            # Steering: as soon as the white line is visible ANYWHERE, steer
            # straight toward it while continuing to drive forward, so the robot
            # converges onto it smoothly (find line top-left/right → curve onto
            # it → follow).
            if white_found and white_err is not None:
                seek_wz = -self._rec_white_kp * float(white_err)   # err>0 (white right)→turn right
                seek_wz = max(-self._rec_white_max, min(self._rec_white_max, seek_wz))
                return self._rec_linear, seek_wz

            # No white yet.  ANTI-CROSS: if the outer boundary is still right
            # ahead/under the nose (dense yellow, or yellow high in the frame),
            # rotate INWARD almost in place instead of driving forward into it —
            # otherwise the forward arc noses across the outer line and leaves the
            # arena (exactly the failure seen in the field).  Only once the
            # boundary is no longer ahead do we arc forward to go find the lane.
            boundary_ahead = (self._ev_side < 0 and
                              (boundary_near or
                               (yellow_cx is not None and yellow_cy_frac is not None
                                and yellow_cy_frac < self._outer_perp_cy)))
            if boundary_ahead:
                return self._cross_guard_vx, self._rec_angular
            return self._rec_linear, self._rec_angular

        # ── RESUMING ─────────────────────────────────────────────────────────
        elif self._state == _RESUMING:
            ramp = min(elapsed / max(self._ramp_dur, 0.1), 1.0)
            if elapsed >= self._ramp_dur:
                self._enter(_NORMAL, now)
                logger.info("Resumed normal lane following")
            # Ramp forward speed up from a floor so the robot never stalls on
            # re-entry, but keep FULL steering authority so it can correct the
            # moment it picks up the line (no ramped-down, under-steering wz).
            vx_scale = self._resume_vx_floor + (1.0 - self._resume_vx_floor) * ramp
            return vx * vx_scale, wz

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

    def _outer_steer(self, yellow_cx: Optional[float],
                     yellow_cy_frac: Optional[float],
                     frame_w: int, base_vx: float,
                     boundary_near: bool = False) -> Tuple[float, float, bool]:
        """
        OUTER-boundary follow controller — used in EVADING (approach) and HOLDING.

        Goal: keep the OUTER yellow boundary on the evasion side of the frame
        (clockwise → LEFT, rel ≈ _ev_yellow_tgt = 0.30) while driving forward,
        never letting yellow reach the centre and never crossing it (so the
        robot stays inside the arena).  Only one track line is visible at a
        time, so during outer evasion the only yellow encountered is the outer
        boundary — the inner island is never in view here.

        Returns (vx, wz, established):
            established — True once the robot is parallel to the boundary with
            yellow held on the evasion side; used to advance EVADING → HOLDING.

        Sign convention: wz > 0 = LEFT.  toward_outer = +self._dir
            clockwise   (_dir=+1): toward_outer = +1 → LEFT  is toward the outer boundary
            counter-cw  (_dir=-1): toward_outer = -1 → RIGHT is toward the outer boundary
        """
        toward_outer = float(self._dir)      # CW(+1): left is toward outer boundary
        target       = self._ev_yellow_tgt   # CW outer → 0.30 (evasion-side third)

        # KEY SAFETY RULE: once the boundary is in view, the robot only ever turns
        # AWAY from it (into the arena) or drives straight — it never turns toward
        # the boundary.  That makes it physically unable to drive across the outer
        # line, and removes the old failure where a far-left yellow lookahead made
        # the robot creep LEFT over the tape.  `turn_away >= 0` is the magnitude of
        # the into-arena turn; the final wz is -toward_outer * turn_away.

        # Latch the boundary the first time we actually see yellow this episode.
        if yellow_cx is not None:
            self._outer_yellow_seen = True

        # (1) No yellow detected this frame.
        if yellow_cx is None:
            if self._outer_yellow_seen:
                # We were tracking the boundary and the detector dropped it — it
                # almost certainly swung up into the cropped top of the frame as we
                # squared up to it (perpendicular on a curve), or just blinked.
                # NEVER arc back toward it; ease AWAY into the arena at reduced
                # speed until it reappears, so we cannot creep across the line.
                return base_vx * 0.5, -toward_outer * self._outer_perp_turn, False
            # Initial approach, boundary not found yet → arc toward it to go find it.
            return base_vx, toward_outer * abs(self._ev_angular), False

        rel      = yellow_cx / float(frame_w)
        e_away   = (rel - target) * toward_outer        # >0 = yellow drifting toward centre
        crossed  = (rel - 0.50) * toward_outer > 0.0    # yellow past centre on the cross side
        near_ctr = abs(rel - 0.50) < self._outer_centre_guard
        perp     = (yellow_cy_frac is not None and yellow_cy_frac < self._outer_perp_cy)

        # (2) About to leave / leaving the arena → turn back inside.  If the tape
        #     is right under the nose (boundary_near) or already across centre,
        #     nearly STOP forward motion and rotate in place so the robot cannot
        #     translate across the outer line while it is turning away.
        if boundary_near or crossed or near_ctr:
            vx = self._cross_guard_vx if (boundary_near or crossed) else base_vx * 0.5
            return vx, -toward_outer * self._outer_centre_turn, False

        # (3) Perpendicular approach: yellow lies across the TOP of the frame
        #     (robot heading head-on into the boundary, typically on a curve).
        #     Turn into the arena so the line swings down to the evasion side and
        #     the robot lines up parallel.  Slowed so it does not cross meanwhile.
        if perp:
            return base_vx * 0.6, -toward_outer * self._outer_perp_turn, False

        # (4) Yellow alongside but drifting toward centre → ease back into the
        #     arena, proportional to how far it has encroached past the target.
        if e_away > self._outer_est_tol:
            turn_away = min(self._outer_follow_kp * (e_away - self._outer_est_tol),
                            self._outer_max_away)
            return base_vx, -toward_outer * turn_away, False

        # (5) Yellow sitting comfortably on the evasion side → drive straight
        #     (parallel follow).  We deliberately do NOT chase a boundary that
        #     curves away — drifting slightly inward is safe; crossing is not.
        return base_vx, 0.0, True

    def _enter(self, state: str, now: float):
        self._state      = state
        self._state_time = now
        if state == _EVADING:
            self._outer_yellow_seen = False   # re-arm boundary lock for this episode
            self._evade_start_t     = now     # start the off-white watchdog clock
        if state == _HOLDING:
            self._passed_stamp = None
            self._clear_stamp  = None
            self._hold_min_gap = 999
        if state == _RECOVERING:
            self._recovery_angle_rad    = 0.0
            self._recovery_gyro_samples = 0
        logger.info("Emergency handler → %s", state)

    def _check_holding(self, now: float, elapsed: float):
        """Decide when HOLDING → RECOVERING."""
        if self._position_known():
            # Track the closest the ambulance actually got during this hold. We
            # only believe it has "passed" once it genuinely approached
            # (gap <= recover_min_gap) and is now ahead. This guards against a
            # stale/again-shifting zone reading flipping behind→ahead and kicking
            # recovery before the ambulance ever reached the car.
            gap = self._amb_gap()
            if gap < self._hold_min_gap:
                self._hold_min_gap = gap
            approached = self._hold_min_gap <= self._recover_min_gap
            if (not self._is_amb_behind()) and approached:
                if self._passed_stamp is None:
                    self._passed_stamp = now
                    logger.info("Ambulance overtook car (closest gap=%d) — grace period starting",
                                self._hold_min_gap)
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

    def _amb_fresh(self, now: float) -> bool:
        """True when we have a recent ambulance position to act on."""
        return self._amb_zone >= 0 and (now - self._amb_time) < self._pos_timeout

    def _watchdog_tripped(self, now: float) -> bool:
        """
        Safety bail-out: once we've been off the white line for evade_watchdog_s
        with NO fresh ambulance data to justify still hiding, give up and recover
        to the white line instead of sitting blind on the boundary.
        """
        if self._evade_watchdog <= 0:
            return False
        return ((now - self._evade_start_t) >= self._evade_watchdog
                and not self._amb_fresh(now))

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
        now = time.monotonic()
        if now - self._last_pos_log_t >= 3.0:   # rate-limit: log at most once per 3 s
            self._last_pos_log_t = now
            if not behind:
                logger.info("Ambulance AHEAD (amb=%d car=%d) — NOT yielding",
                            self._amb_zone, self._own_zone)
            elif gap > self._yield_gap:
                logger.info("Ambulance %d zones behind (> %d gap) — not yielding yet",
                            gap, self._yield_gap)
        return False
