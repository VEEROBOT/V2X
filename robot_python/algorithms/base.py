#!/usr/bin/env python3
"""
Abstract base class for lane-following algorithms.

Each algorithm must implement:
  process(frame)   → (vx_m_s, wz_rad_s)
  get_mode()       → 'WHITE' | 'YELLOW' | 'LOST' | 'INIT'
  get_debug_info() → {'mode': str, 'white_err': int|None, 'last_wz': float}
  get_roi_panels() → BGR ndarray (left=annotated ROI, right=HSV mask) or None

Common colour detection (_compute_masks) lives here so every algorithm
shares identical HSV thresholding without code duplication.
"""

from abc import ABC, abstractmethod
from typing import Optional, Tuple

import cv2
import numpy as np


class BaseFollower(ABC):

    def __init__(self, *,
                 linear_speed:      float = 0.10,
                 max_angular_speed: float = 0.90,
                 crop_top_ratio:    float = 0.30,
                 min_contour_area:  int   = 150,
                 lane_offset_px:    float = 0.0,
                 white_hsv_low:   Tuple = (0,   0, 150),
                 white_hsv_high:  Tuple = (180, 70, 255),
                 yellow_hsv_low:  Tuple = (20,  80,  80),
                 yellow_hsv_high: Tuple = (35, 255, 255),
                 cyan_hsv_low:    Tuple = (80,  80,  80),
                 cyan_hsv_high:   Tuple = (100, 255, 255),
                 yellow_repel_frac: float = 0.65,
                 lost_linear_frac:  float = 0.50,
                 lost_stop_s:       float = 4.0,
                 no_white_stop_s:   float = 8.0,
                 debug:             bool  = False):

        self._linear_speed    = linear_speed
        self._max_angular     = max_angular_speed
        self._crop_top        = crop_top_ratio
        self._min_area        = min_contour_area
        self._lane_offset     = float(lane_offset_px)
        self._white_lo        = np.array(white_hsv_low,   dtype=np.uint8)
        self._white_hi        = np.array(white_hsv_high,  dtype=np.uint8)
        self._yellow_lo       = np.array(yellow_hsv_low,  dtype=np.uint8)
        self._yellow_hi       = np.array(yellow_hsv_high, dtype=np.uint8)
        self._cyan_lo         = np.array(cyan_hsv_low,    dtype=np.uint8)
        self._cyan_hi         = np.array(cyan_hsv_high,   dtype=np.uint8)
        self._repel_frac      = float(yellow_repel_frac)
        self._lost_lin_frac   = float(lost_linear_frac)
        self._lost_stop_s     = float(lost_stop_s)
        self._no_white_stop_s = float(no_white_stop_s)
        self._debug           = debug

        # Shared PID / steering state
        self._prev_error     = 0.0
        self._integral       = 0.0
        self._last_wz        = 0.0
        self._lost_start     = None
        self._no_white_start = None
        self._mode           = 'INIT'

        # Last frame data (used by get_roi_panels / get_debug_info)
        self._last_roi    = None
        self._last_mask_w = None
        self._last_mask_y = None
        self._last_cx     = None   # white x-position (meaning depends on algorithm)
        self._last_ycx    = None   # yellow centroid x

    # ── Abstract interface ───────────────────────────────────────────────────
    @abstractmethod
    def process(self, frame) -> Tuple[float, float]:
        ...

    @abstractmethod
    def get_mode(self) -> str:
        ...

    @abstractmethod
    def get_debug_info(self) -> dict:
        ...

    @abstractmethod
    def get_roi_panels(self) -> Optional[np.ndarray]:
        ...

    def reset_pid(self):
        self._integral       = 0.0
        self._prev_error     = 0.0
        self._last_wz        = 0.0
        self._lost_start     = None
        self._no_white_start = None

    # ── Shared colour detection ──────────────────────────────────────────────
    def _compute_masks(self, roi):
        """
        Return (white_mask, yellow_mask).
        yellow_mask includes cyan range — catches yellow tape that AWB shifts to teal.
        Stores results in _last_mask_w / _last_mask_y for get_roi_panels().
        """
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        mw  = cv2.inRange(hsv, self._white_lo,  self._white_hi)
        my  = cv2.inRange(hsv, self._yellow_lo, self._yellow_hi)
        mc  = cv2.inRange(hsv, self._cyan_lo,   self._cyan_hi)
        self._last_mask_w = mw
        self._last_mask_y = my | mc
        return mw, my | mc

    def _yellow_centroid(self, mask) -> Optional[float]:
        """Uniform-weight centroid for yellow — only left/right direction matters."""
        m = cv2.erode(mask, None, iterations=1)
        m = cv2.dilate(m,   None, iterations=2)
        M = cv2.moments(m)
        if M['m00'] < self._min_area * 10:
            return None
        return M['m10'] / M['m00']
