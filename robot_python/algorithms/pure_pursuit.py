#!/usr/bin/env python3
"""
File: pure_pursuit.py
Module: V2X Robot Platform — Pure Pursuit Lane Follower Algorithm

Purpose:
    Geometric lane-following algorithm based on the Pure Pursuit controller.
    Scans the ROI in horizontal strips to find a lookahead point on the white
    line and steers using curvature = 2*Lx/(Lx²+Ly²). Starts turning earlier
    on curves than centroid, requires only one gain (kpp), and naturally slows
    on sharp bends.

Author(s): Praveen Kumar
Company: Siliris Technologies Pvt. Ltd
Created: 1st March 2026
Version: 1.0

Key Parameters:
    kpp            — steering gain (raise if too gentle, lower if oscillating)
    lookahead_frac — fraction of ROI height for lookahead (0.3 aggressive,
                     0.6 smooth)

License:
    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
    Proprietary - See LICENSE file for terms and conditions.
"""

import logging
import math
import time
from typing import List, Optional, Tuple

import cv2
import numpy as np

from .base import BaseFollower

logger = logging.getLogger(__name__)

_N_STRIPS = 16   # number of horizontal scan strips across the ROI


class PurePursuitFollower(BaseFollower):

    def __init__(self, *,
                 kpp:            float = 50.0,
                 lookahead_frac: float = 0.50,
                 ly_min_px:      float = 35.0,
                 heading_kp:     float = 0.0,
                 gyro_hold_kp:   float = 0.0,
                 gyro_max_rad_s: float = 4.0,
                 **kwargs):
        super().__init__(**kwargs)
        self._kpp            = kpp
        self._lookahead_frac = lookahead_frac
        self._ly_min         = float(ly_min_px)
        self._heading_kp     = float(heading_kp)      # curve anticipation from line angle
        self._gyro_hold_kp   = float(gyro_hold_kp)    # yaw-rate hold gain while line lost
        self._gyro_max_rate  = float(gyro_max_rad_s)  # spike rejection for gyro
        self._smoothed_slope = 0.0
        self._slope_alpha    = 0.5
        self._last_points:    List[Tuple[float, float]] = []   # (row_from_bottom, cx)
        self._last_lookahead: Optional[Tuple[float, float]] = None  # (Lx, Ly)
        self._last_n_strips:  int = 0
        self._last_good_wz:   float = 0.0
        self._last_good_lx:   float = 0.0
        self._last_good_conf: float = 0.0
        self._lx_alpha       = 0.55      # EMA factor for lookahead error smoothing
        self._smoothed_lx    = 0.0
        self._wz_slew        = 0.12      # max |Δwz| per frame @ 20 Hz

        # Yellow Pure Pursuit state — updated every process() call
        self._last_yellow_points:    List[Tuple[float, float]] = []
        self._last_yellow_lookahead: Optional[Tuple[float, float]] = None  # (cx_at_lookahead, ly)

    # ── Public API ───────────────────────────────────────────────────────────
    def get_mode(self) -> str:
        return self._mode

    def get_debug_info(self) -> dict:
        roi_w  = self._last_roi.shape[1] if self._last_roi is not None else 320
        target = roi_w / 2.0 + self._lane_offset
        # Report lateral offset at lookahead point as the "error" equivalent
        if self._last_lookahead is not None:
            lx, ly = self._last_lookahead
            white_err = int(lx)
            ly_px     = int(ly)
        else:
            white_err = None
            ly_px     = None
        return {
            'mode':          self._mode,
            'white_err':     white_err,
            'ly_px':         ly_px,
            'n_strips':      self._last_n_strips,
            'last_wz':       round(self._last_wz, 3),
            'yellow_cx':     self._last_ycx,
            'yellow_cy_frac': self._last_ycy,   # 0.0=top(far/ahead), 1.0=bottom(near/alongside)
        }

    def process(self, frame) -> Tuple[float, float]:
        h, w  = frame.shape[:2]
        roi   = frame[int(h * self._crop_top):, :]
        self._last_roi = roi

        mask_w, mask_y = self._compute_masks(roi)
        yellow_cx = self._yellow_centroid(mask_y)
        self._last_ycx = yellow_cx

        roi_h  = roi.shape[0]
        roi_w  = roi.shape[1]
        target = roi_w / 2.0 + self._lane_offset
        now    = time.monotonic()

        # Yellow Pure Pursuit lookahead — updated every frame so the emergency
        # handler gets a look-ahead cx instead of the raw bottom-of-frame centroid.
        self._update_yellow_lookahead(mask_y, roi_w, roi_h)

        # Scan the white mask in horizontal strips
        points = self._scan_strips(mask_w, roi_w)
        self._last_points   = points
        self._last_n_strips = len(points)

        white_found = len(points) > 0
        self._last_cx = points[0][1] if points else None  # near-most point for logging

        # Combined no-white timer
        if not white_found:
            if self._no_white_start is None:
                self._no_white_start = now
            if (now - self._no_white_start) >= self._no_white_stop_s:
                self._mode = 'LOST'
                self._last_lookahead = None
                return 0.0, 0.0
        else:
            self._no_white_start = None

        # ── Priority 1: white line ───────────────────────────────────────────
        if white_found:
            lookahead_px = roi_h * self._lookahead_frac
            lx, ly = self._get_lookahead(points, target, lookahead_px)
            n_strips = len(points)

            # Smooth lookahead error: strip centroids are noisy and can make the
            # controller chase jitter.
            self._smoothed_lx = self._lx_alpha * lx + (1.0 - self._lx_alpha) * self._smoothed_lx
            lx = self._smoothed_lx

            edge_conf = abs(lx) > roi_w * 0.40
            edge_track = edge_conf and n_strips >= 6 and ly >= self._ly_min
            low_conf = n_strips <= 4 or ly < self._ly_min
            sign_flip = (
                self._last_good_conf > 0.0
                and np.sign(lx) != np.sign(self._last_good_lx)
                and abs(lx) > 20.0
                and abs(self._last_good_lx) > 20.0
            )
            if low_conf and sign_flip:
                lx = self._last_good_lx

            self._last_lookahead = (lx, ly)

            self._lost_start = None
            self._mode = 'WHITE'

            # Pure pursuit curvature and angular rate.
            # ly_min prevents formula blow-up when only near strips detected.
            ly_safe = max(ly, self._ly_min)
            l_sq = lx * lx + ly_safe * ly_safe
            curvature = (2.0 * lx / l_sq) if l_sq > 1.0 else 0.0

            # Heading/angle feed-forward: fit the strip centroids and steer on the
            # line's tangent too, not just the lookahead offset. slope = d(cx)/d(row)
            # > 0 means the line leans right as it recedes (curve turning right
            # ahead) → add right turn. Anticipates curves so the robot starts the
            # turn earlier instead of drifting wide then correcting late.
            heading_wz = 0.0
            if self._heading_kp > 0.0 and n_strips >= 4:
                rows = np.array([p[0] for p in points], dtype=np.float64)
                cxs  = np.array([p[1] for p in points], dtype=np.float64)
                slope = float(np.polyfit(rows, cxs, 1)[0])
                self._smoothed_slope = (self._slope_alpha * slope
                                        + (1.0 - self._slope_alpha) * self._smoothed_slope)
                heading_wz = -self._heading_kp * self._smoothed_slope
            else:
                self._smoothed_slope = 0.0

            wz = float(np.clip(-self._kpp * curvature + heading_wz,
                                -self._max_angular, self._max_angular))

            if n_strips <= 3:
                wz = float(np.clip(wz, -0.35, 0.35))
            elif n_strips <= 5:
                wz = float(np.clip(wz, -0.55, 0.55))
            elif edge_track:
                # Edge-visible line on a curve is often legitimate; boost turn authority
                # instead of under-steering away from the dashed guide.
                min_edge_wz = min(self._max_angular, 0.65)
                if abs(wz) < min_edge_wz:
                    wz = float(np.sign(wz) * min_edge_wz)

            # Slew rate limit — 4-wheel robots have high inertia and skid if
            # steering changes too abruptly.
            delta_wz = wz - self._last_wz
            if abs(delta_wz) > self._wz_slew:
                wz = self._last_wz + math.copysign(self._wz_slew, delta_wz)

            self._last_wz = wz

            if n_strips >= 6 and ly >= self._ly_min:
                self._last_good_wz = wz
                self._last_good_lx = lx
                self._last_good_conf = 1.0

            # Speed: gentle reduction so inner wheel stays above IK-clamp threshold.
            # 0.70 was too aggressive — at max error vx dropped to 0.03 m/s, clamping
            # the inner wheel to 0 and killing turning ability.
            err_ratio = min(abs(lx) / 120.0, 1.0)
            vx_cmd = self._linear_speed * (1.0 - 0.40 * err_ratio)
            return vx_cmd, wz

        # ── Priority 2: yellow boundary — repel ─────────────────────────────
        if yellow_cx is not None:
            self._lost_start = None
            self._mode = 'YELLOW'
            self._last_lookahead = None
            self._prev_error = 0.0
            self._integral   = 0.0
            wz = float(np.sign(yellow_cx - target) * self._max_angular * self._repel_frac)
            wz = float(np.clip(wz, -self._max_angular, self._max_angular))
            self._last_wz = wz
            return self._linear_speed * 0.5, wz

        # ── Priority 3: LOST — carry last steering, then active search sweep ──
        if self._lost_start is None:
            self._lost_start = now
        self._mode = 'LOST'
        self._last_lookahead = None
        elapsed = now - self._lost_start
        if elapsed >= self._lost_stop_s:
            self._last_wz = 0.0
            return 0.0, 0.0
        if elapsed >= self._search_delay_s:
            vx, wz = self._lost_search_tick(now)
            self._last_wz = wz
            return vx, wz
        # Brief gap: instead of replaying last_good_wz open-loop (which wanders as
        # the wheels skid), hold the intended turn-rate closed-loop on the gyro —
        # command wz so the measured yaw-rate tracks the last good rate. Keeps a
        # straight section straight and a curve on its arc through the gap.
        target = float(np.clip(self._last_good_wz, -0.55, 0.55))
        if self._gyro_hold_kp > 0.0 and 0.02 < abs(self._gyro_z) <= self._gyro_max_rate:
            hold_wz = target + self._gyro_hold_kp * (target - self._gyro_z)
            hold_wz = float(np.clip(hold_wz, -0.55, 0.55))
        else:
            hold_wz = target
        self._last_wz = hold_wz
        return self._linear_speed * self._lost_lin_frac, hold_wz

    # ── Debug panel ──────────────────────────────────────────────────────────
    def get_roi_panels(self) -> Optional[np.ndarray]:
        if self._last_roi is None:
            return None
        roi = self._last_roi
        h, w = roi.shape[:2]
        target = int(w / 2 + self._lane_offset)

        left = roi.copy()
        cv2.line(left, (w // 2, 0), (w // 2, h), (0, 200, 0),   1)
        cv2.line(left, (target,  0), (target,  h), (0, 165, 255), 1)

        # Draw each detected strip centroid as a small dot
        for row_from_bottom, cx in self._last_points:
            row_from_top = int(h - row_from_bottom)
            cv2.circle(left, (int(cx), row_from_top), 3, (180, 180, 0), -1)

        # Draw lookahead point larger and in red
        if self._last_lookahead is not None:
            lx, ly = self._last_lookahead
            lp_x = int(target + lx)
            lp_y = int(h - ly)
            lp_x = max(0, min(w - 1, lp_x))
            lp_y = max(0, min(h - 1, lp_y))
            cv2.circle(left, (lp_x, lp_y), 7, (0, 0, 255), -1)
            cv2.putText(left, f"Lx={int(lx):+d}", (2, 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 255), 1)

        # Raw yellow centroid (small dot, for comparison)
        if self._last_ycx is not None:
            cv2.circle(left, (int(self._last_ycx), h * 3 // 4), 4, (0, 215, 255), -1)

        # Yellow Pure Pursuit overlay: strip centroids + lookahead point
        y_target_px = int(w * self._yellow_target_frac)
        cv2.line(left, (y_target_px, 0), (y_target_px, h), (0, 160, 215), 1)  # yellow target line
        for row_from_bottom, cx in self._last_yellow_points:
            row_from_top = int(h - row_from_bottom)
            cv2.circle(left, (int(cx), row_from_top), 2, (0, 160, 215), -1)   # yellow strip dots
        if self._last_yellow_lookahead is not None:
            ycx_la, yla = self._last_yellow_lookahead
            ylp_x = max(0, min(w - 1, int(ycx_la)))
            ylp_y = max(0, min(h - 1, int(h - yla)))
            cv2.circle(left, (ylp_x, ylp_y), 6, (0, 100, 255), 2)             # yellow lookahead ring
            cv2.putText(left, f"Ylo={int(ycx_la)}", (2, 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 160, 215), 1)

        mode_col = {'WHITE': (0,255,0), 'YELLOW': (0,215,255),
                    'LOST': (0,0,255), 'INIT': (128,128,128)}.get(self._mode, (128,128,128))
        cv2.putText(left, f"PURSUIT {self._mode}", (2, h - 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.3, mode_col, 1)

        right = np.zeros_like(roi)
        if self._last_mask_w is not None:
            right[self._last_mask_w > 0] = (220, 220, 220)
        if self._last_mask_y is not None:
            right[self._last_mask_y > 0] = (0, 215, 255)
        cv2.putText(right, "HSV MASK", (2, h - 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.3, (140, 140, 140), 1)

        return np.hstack([left, right])

    # ── Private ──────────────────────────────────────────────────────────────
    def _scan_strips(self, mask_w, roi_w: int) -> List[Tuple[float, float]]:
        """
        Divide the white mask into _N_STRIPS horizontal bands.
        For each band with enough white pixels, compute the centroid X.
        Returns list of (row_from_bottom, centroid_x) sorted bottom→top.
        """
        h = mask_w.shape[0]
        strip_h = max(1, h // _N_STRIPS)
        cols = np.arange(roi_w, dtype=np.float64)
        points = []

        for i in range(_N_STRIPS):
            y1 = h - i * strip_h
            y0 = max(0, y1 - strip_h)
            if y0 >= y1:
                continue
            strip = mask_w[y0:y1, :]
            col_sum = strip.sum(axis=0).astype(np.float64)
            total = col_sum.sum()
            if total < self._min_area * 255 * 0.2:   # ~20% of min_area threshold
                continue
            cx = (col_sum * cols).sum() / total
            row_from_bottom = h - (y0 + y1) / 2.0
            points.append((row_from_bottom, cx))

        return points  # already sorted bottom→top (i=0 is bottom)

    def _get_lookahead(self, points: List[Tuple[float, float]],
                       target: float, lookahead_px: float) -> Tuple[float, float]:
        """
        Interpolate (or extrapolate) to find the line position at exactly
        lookahead_px rows ahead.  Returns (Lx, Ly): lateral offset and
        actual forward distance used for the Pure Pursuit formula.
        """
        if len(points) == 1:
            row, cx = points[0]
            return cx - target, row

        # Sort bottom (near) to top (far)
        pts = sorted(points, key=lambda p: p[0])

        below = [(r, x) for r, x in pts if r <= lookahead_px]
        above = [(r, x) for r, x in pts if r >= lookahead_px]

        if not above:
            # All detected points are closer than the lookahead — use the farthest
            r, cx = pts[-1]
            return cx - target, r

        if not below:
            # All detected points are farther than the lookahead — use the nearest
            r, cx = pts[0]
            return cx - target, r

        # Linear interpolation between the two closest surrounding points
        r0, x0 = below[-1]
        r1, x1 = above[0]
        if r1 == r0:
            cx = (x0 + x1) / 2.0
        else:
            t  = (lookahead_px - r0) / (r1 - r0)
            cx = x0 + t * (x1 - x0)

        return cx - target, lookahead_px

    def _update_yellow_lookahead(self, mask_y, roi_w: int, roi_h: int):
        """
        Scan the yellow mask in horizontal strips (same as white), find the
        interpolated yellow-line position at the lookahead distance, and cache
        the result as self._yellow_lookahead_cx (absolute pixel x).

        This gives the emergency_handler a look-ahead cx instead of the raw
        bottom-of-frame centroid, enabling proper oval-curve anticipation during
        EVADING phase 2 and HOLDING.  Falls back to None (centroid used instead)
        when yellow is not detected in enough strips.
        """
        points = self._scan_strips(mask_y, roi_w)
        self._last_yellow_points = points

        if not points:
            self._yellow_lookahead_cx   = None
            self._last_yellow_lookahead = None
            return

        # Robust vertical position of the yellow line from the (non-eroded) strip
        # scan. The eroded moments centroid in _yellow_centroid drops thin / distant
        # lines — exactly the perpendicular boundary seen across the TOP of the frame
        # on a curve — and reports cy=None, so the evasion controller never realises
        # "yellow is ahead" and drives across it. Strip rows are reliable here:
        # row_from_bottom ≈ roi_h at the TOP (far / ahead), ≈ 0 at the BOTTOM (near).
        mean_row = sum(r for r, _ in points) / len(points)
        self._last_ycy = max(0.0, min(1.0, 1.0 - mean_row / float(roi_h)))

        lookahead_px = roi_h * self._lookahead_frac
        # _get_lookahead returns (cx - target, ly). Pass target=0 → returns absolute cx.
        cx_abs, ly = self._get_lookahead(points, target=0.0, lookahead_px=lookahead_px)
        self._last_yellow_lookahead  = (cx_abs, ly)
        self._yellow_lookahead_cx    = cx_abs
