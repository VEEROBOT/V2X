#!/usr/bin/env python3
"""
Pure Pursuit lane follower.

Instead of a single averaged centroid, the ROI is scanned in horizontal
strips to build a list of (row_from_bottom, centroid_x) points along the
detected white line.  A "lookahead point" is selected at a configurable
distance ahead of the robot.  Steering is computed using the Pure Pursuit
geometric formula:

    curvature = 2 * Lx / (Lx² + Ly²)
    wz        = -kpp * curvature

where Lx is the lateral offset of the lookahead point and Ly is its
forward distance (both in pixels).

Advantages over centroid
  • The robot starts turning earlier on curves because the lookahead point
    is already displaced before the curve apex.
  • No PID integral/derivative — one tuning knob (kpp) instead of three.
  • Speed naturally scales with curvature (sharper curve → slower).

Key tuning parameters
  kpp           — gain; raise if turning is too gentle, lower if oscillating.
  lookahead_frac — fraction of ROI height used as lookahead distance.
                   0.3 = aggressive (short lookahead, quick response),
                   0.6 = smooth (longer lookahead, gentler curves).
"""

import logging
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
                 **kwargs):
        super().__init__(**kwargs)
        self._kpp            = kpp
        self._lookahead_frac = lookahead_frac
        self._ly_min         = float(ly_min_px)
        self._last_points:    List[Tuple[float, float]] = []   # (row_from_bottom, cx)
        self._last_lookahead: Optional[Tuple[float, float]] = None  # (Lx, Ly)
        self._last_n_strips:  int = 0
        self._last_good_wz:   float = 0.0
        self._last_good_lx:   float = 0.0
        self._last_good_conf: float = 0.0

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
            'mode':      self._mode,
            'white_err': white_err,
            'ly_px':     ly_px,
            'n_strips':  self._last_n_strips,
            'last_wz':   round(self._last_wz, 3),
            'yellow_cx': self._last_ycx,
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
            wz = float(np.clip(-self._kpp * curvature,
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

        # ── Priority 3: LOST — carry last steering ───────────────────────────
        if self._lost_start is None:
            self._lost_start = now
        self._mode = 'LOST'
        self._last_lookahead = None
        if now - self._lost_start >= self._lost_stop_s:
            return 0.0, 0.0
        safe_wz = float(np.clip(self._last_good_wz, -0.55, 0.55))
        return self._linear_speed * self._lost_lin_frac, safe_wz

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

        if self._last_ycx is not None:
            cv2.circle(left, (int(self._last_ycx), h * 3 // 4), 6, (0, 215, 255), -1)

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
