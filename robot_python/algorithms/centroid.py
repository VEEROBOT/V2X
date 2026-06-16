#!/usr/bin/env python3
"""
File: centroid.py
Module: V2X Robot Platform — Centroid Lane Follower Algorithm

Purpose:
    Original lane-following algorithm. Detects the white line centroid across
    the full ROI (bottom-weighted so near rows count 4× more than far rows)
    and applies a PD controller to steer toward it. Simple and robust on
    straights; may under-steer on tight curves due to centroid averaging.

Author(s): Praveen Kumar
Company: Siliris Technologies Pvt. Ltd
Created: 1st March 2026
Version: 1.0

License:
    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
    Proprietary - See LICENSE file for terms and conditions.
"""

import logging
import time
from typing import Optional, Tuple

import cv2
import numpy as np

from .base import BaseFollower

logger = logging.getLogger(__name__)


class CentroidFollower(BaseFollower):

    def __init__(self, *,
                 kp: float = 0.007,
                 ki: float = 0.0,
                 kd: float = 0.0,
                 **kwargs):
        super().__init__(**kwargs)
        self._kp        = kp
        self._ki        = ki
        self._kd        = kd
        self._last_time = time.monotonic()

    # ── Public API ───────────────────────────────────────────────────────────
    def get_mode(self) -> str:
        return self._mode

    def get_debug_info(self) -> dict:
        roi_w  = self._last_roi.shape[1] if self._last_roi is not None else 320
        target = roi_w / 2.0 + self._lane_offset
        white_err = int(self._last_cx - target) if self._last_cx is not None else None
        return {
            'mode':      self._mode,
            'white_err': white_err,
            'ly_px':     None,    # N/A for centroid
            'n_strips':  None,    # N/A for centroid
            'last_wz':   round(self._last_wz, 3),
            'yellow_cx': self._last_ycx,
            'yellow_cy_frac': self._last_ycy,   # 0.0=top(far/ahead), 1.0=bottom(near/alongside)
        }

    def process(self, frame) -> Tuple[float, float]:
        h, w  = frame.shape[:2]
        roi   = frame[int(h * self._crop_top):, :]
        self._last_roi = roi

        mask_w, mask_y = self._compute_masks(roi)
        white_cx  = self._centroid_x(mask_w)
        yellow_cx = self._yellow_centroid(mask_y)
        self._last_cx  = white_cx
        self._last_ycx = yellow_cx

        roi_w  = roi.shape[1]
        target = roi_w / 2.0 + self._lane_offset
        now    = time.monotonic()

        # Combined no-white timer — spans YELLOW and LOST together
        if white_cx is None:
            if self._no_white_start is None:
                self._no_white_start = now
            if (now - self._no_white_start) >= self._no_white_stop_s:
                self._mode = 'LOST'
                return 0.0, 0.0
        else:
            self._no_white_start = None

        # ── Priority 1: white line ───────────────────────────────────────────
        if white_cx is not None:
            error = white_cx - target

            if self._mode != 'WHITE':
                # Re-acquiring — zero derivative state to prevent spike
                self._prev_error = error
                self._integral   = 0.0
                self._last_time  = now

            self._lost_start = None
            self._mode = 'WHITE'

            dt = max(now - self._last_time, 0.01)
            self._last_time = now

            self._integral  += error * dt
            derivative       = (error - self._prev_error) / dt
            self._prev_error = error

            wz = -(self._kp * error + self._ki * self._integral + self._kd * derivative)
            wz = float(np.clip(wz, -self._max_angular, self._max_angular))
            self._last_wz = wz

            err_ratio = min(abs(error) / 120.0, 1.0)
            vx_cmd = self._linear_speed * (1.0 - 0.70 * err_ratio)
            return vx_cmd, wz

        # ── Priority 2: yellow boundary — repel ─────────────────────────────
        if yellow_cx is not None:
            self._lost_start = None
            self._mode = 'YELLOW'
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
        elapsed = now - self._lost_start
        if elapsed >= self._lost_stop_s:
            return 0.0, 0.0
        if elapsed >= self._search_delay_s:
            vx, wz = self._lost_search_tick(now)
            self._last_wz = wz
            return vx, wz
        return self._linear_speed * self._lost_lin_frac, self._last_wz

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

        if self._last_cx is not None:
            cx = int(self._last_cx)
            cv2.circle(left, (cx, h // 2), 6, (0, 0, 255), -1)
            err = int(self._last_cx - target)
            cv2.putText(left, f"err={err:+d}", (2, 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 255), 1)

        if self._last_ycx is not None:
            cv2.circle(left, (int(self._last_ycx), h * 3 // 4), 6, (0, 215, 255), -1)

        mode_col = {'WHITE': (0,255,0), 'YELLOW': (0,215,255),
                    'LOST': (0,0,255), 'INIT': (128,128,128)}.get(self._mode, (128,128,128))
        cv2.putText(left, f"CENTROID {self._mode}", (2, h - 3),
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
    def _centroid_x(self, mask) -> Optional[float]:
        m = cv2.erode(mask, None, iterations=1)
        m = cv2.dilate(m,   None, iterations=2)

        contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        valid = [c for c in contours if cv2.contourArea(c) >= self._min_area]
        if not valid:
            return None

        h, w = m.shape
        clean = np.zeros_like(m)
        cv2.drawContours(clean, valid, -1, 255, -1)

        row_w   = np.linspace(0.25, 1.0, h, dtype=np.float64).reshape(-1, 1)
        wgt     = clean.astype(np.float64) * row_w
        m00     = wgt.sum()
        if m00 == 0:
            return None
        col_idx = np.arange(w, dtype=np.float64).reshape(1, -1)
        return (wgt * col_idx).sum() / m00
