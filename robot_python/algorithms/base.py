#!/usr/bin/env python3
"""
File: base.py
Module: V2X Robot Platform — Lane Follower Base Class

Purpose:
    Abstract base class that defines the interface all lane-following
    algorithms must implement. Provides shared HSV colour thresholds,
    crop parameters, speed limits, and lost-line timeout logic.

Author(s): Praveen Kumar
Company: Siliris Technologies Pvt. Ltd
Created: 1st March 2026
Version: 1.0

License:
    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
    Proprietary - See LICENSE file for terms and conditions.
"""

from abc import ABC, abstractmethod
from typing import Optional, Tuple

import cv2
import numpy as np


class BaseFollower(ABC):

    def __init__(self, *,
                 linear_speed:       float = 0.10,
                 max_angular_speed:  float = 0.90,
                 crop_top_ratio:     float = 0.30,
                 min_contour_area:   int   = 150,
                 lane_offset_px:     float = 0.0,
                 driving_direction:  str   = 'clockwise',
                 white_hsv_low:   Tuple = (0,   0, 150),
                 white_hsv_high:  Tuple = (180, 70, 255),
                 yellow_hsv_low:  Tuple = (20,  80,  80),
                 yellow_hsv_high: Tuple = (35, 255, 255),
                 cyan_hsv_low:    Tuple = (80,  80,  80),
                 cyan_hsv_high:   Tuple = (100, 255, 255),
                 green_hsv_low:   Tuple = (40,  80,  80),
                 green_hsv_high:  Tuple = (80, 255, 255),
                 blue_hsv_low:    Tuple = (100, 80,  80),
                 blue_hsv_high:   Tuple = (130, 255, 255),
                 yellow_repel_frac: float = 0.65,
                 green_repel_frac:  float = 0.40,
                 blue_repel_frac:   float = 0.40,
                 lost_linear_frac:    float = 0.50,
                 lost_stop_s:         float = 4.0,
                 no_white_stop_s:     float = 8.0,
                 lost_search_delay_s: float = 1.5,
                 lost_search_turn_spd:float = 0.40,
                 lost_search_arm_s:   float = 0.8,
                 lost_search_fwd_s:   float = 0.4,
                 debug:               bool  = False):

        self._linear_speed    = linear_speed
        self._max_angular     = max_angular_speed
        self._crop_top        = crop_top_ratio
        self._min_area        = min_contour_area
        self._lane_offset     = float(lane_offset_px)
        # +1 = clockwise (inner island to RIGHT → inward = right → wz < 0)
        # -1 = counterclockwise (inner island to LEFT → inward = left → wz > 0)
        self._dir = +1 if driving_direction.lower().startswith('c') and 'counter' not in driving_direction.lower() else -1
        self._white_lo        = np.array(white_hsv_low,   dtype=np.uint8)
        self._white_hi        = np.array(white_hsv_high,  dtype=np.uint8)
        self._yellow_lo       = np.array(yellow_hsv_low,  dtype=np.uint8)
        self._yellow_hi       = np.array(yellow_hsv_high, dtype=np.uint8)
        self._cyan_lo         = np.array(cyan_hsv_low,    dtype=np.uint8)
        self._cyan_hi         = np.array(cyan_hsv_high,   dtype=np.uint8)
        self._green_lo        = np.array(green_hsv_low,   dtype=np.uint8)
        self._green_hi        = np.array(green_hsv_high,  dtype=np.uint8)
        self._blue_lo         = np.array(blue_hsv_low,    dtype=np.uint8)
        self._blue_hi         = np.array(blue_hsv_high,   dtype=np.uint8)
        self._repel_frac      = float(yellow_repel_frac)
        self._green_repel     = float(green_repel_frac)
        self._blue_repel      = float(blue_repel_frac)
        self._lost_lin_frac      = float(lost_linear_frac)
        self._lost_stop_s        = float(lost_stop_s)
        self._no_white_stop_s    = float(no_white_stop_s)
        self._search_delay_s     = float(lost_search_delay_s)
        self._search_turn_spd    = float(lost_search_turn_spd)
        self._search_arm_s       = float(lost_search_arm_s)
        self._search_fwd_s       = float(lost_search_fwd_s)
        self._debug              = debug

        # Shared PID / steering state
        self._prev_error     = 0.0
        self._integral       = 0.0
        self._last_wz        = 0.0
        self._lost_start     = None
        self._no_white_start = None
        self._mode           = 'INIT'

        # Lost-line search sweep state
        self._search_phase   = 0    # 0=left, 1=right, 2=return-left, 3=forward
        self._search_phase_t = 0.0  # monotonic timestamp of phase start (0 = not started)

        # Last frame data (used by get_roi_panels / get_debug_info)
        self._last_roi    = None
        self._last_mask_w = None
        self._last_mask_y = None
        self._last_mask_g = None   # green shoulder mask
        self._last_mask_b = None   # blue shoulder mask
        self._last_cx     = None   # white x-position (meaning depends on algorithm)
        self._last_ycx    = None   # yellow centroid x
        self._last_ycy: Optional[float] = None   # yellow centroid y, normalised 0=top 1=bottom
        self._last_gcx: Optional[float] = None   # green centroid x
        self._last_gcy: Optional[float] = None   # green centroid y, normalised 0=top 1=bottom
        self._last_bcx: Optional[float] = None   # blue centroid x

        # Yellow Pure Pursuit lookahead — set by subclasses that implement it
        self._yellow_lookahead_cx: Optional[float] = None

        # Latest IMU yaw-rate (rad/s), pushed in each frame via set_gyro().
        # Used for gyro heading-hold while the line is briefly lost.
        self._gyro_z: float = 0.0
        self._yellow_target_frac: float = 0.70   # updated via set_yellow_target()

        # Current zone — updated by main_car via set_zone() each loop tick
        self._current_zone = -1

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

    def set_zone(self, zone: int):
        """Called by main_car each loop tick so algorithms can use zone info."""
        self._current_zone = zone

    def set_yellow_target(self, frac: float):
        """
        Set the frame-fraction where yellow should appear during evasion (0.0–1.0).
        Should match emergency_handler.evasion_yellow_target so both controllers
        use the same reference point.  Called once at startup from main_car.py.
        """
        self._yellow_target_frac = float(frac)

    def get_yellow_lookahead_cx(self) -> Optional[float]:
        """
        Pixel x of the yellow line at the Pure Pursuit lookahead distance.
        None if yellow was not found in the last frame.

        PurePursuitFollower computes this after every process() call.
        CentroidFollower returns None (falls back to raw centroid in main_car).
        The emergency_handler uses this in place of the raw centroid during
        EVADING phase 2 and HOLDING so the P-controller reacts to a look-ahead
        point rather than the nearest yellow pixels.
        """
        return self._yellow_lookahead_cx

    def set_gyro(self, gyro_z: float) -> None:
        """Push the latest IMU yaw-rate (rad/s) for gyro heading-hold in gaps."""
        self._gyro_z = float(gyro_z)

    def is_boundary_near(self) -> bool:
        """
        True when yellow tape is DENSE in the bottom quarter of the ROI (very close
        to the robot).  Used by emergency_handler to detect when the robot has
        physically reached the inner island tape during EVADING.

        Threshold raised from ×2 to ×8 so the robot must be close enough that the
        tape fills a meaningful area — prevents the check firing during normal driving
        when the inner island is merely visible at the edge of the frame.
        """
        if self._last_mask_y is None:
            return False
        h = self._last_mask_y.shape[0]
        near = self._last_mask_y[3 * h // 4:, :]   # bottom QUARTER = very close to robot
        return int(near.sum()) > self._min_area * 255 * 8

    def reset_pid(self):
        self._integral       = 0.0
        self._prev_error     = 0.0
        self._last_wz        = 0.0
        self._lost_start     = None
        self._no_white_start = None
        self._search_phase   = 0
        self._search_phase_t = 0.0

    def _lost_search_tick(self, now: float) -> Tuple[float, float]:
        """
        Oscillating sweep when LOST beyond search_delay_s.

        Pattern (repeating):
          Phase 0  search_arm_s    : in-place left turn  (+wz)
          Phase 1  search_arm_s×2  : in-place right turn (−wz, crosses center)
          Phase 2  search_arm_s    : in-place left turn  (+wz, returns to heading)
          Phase 3  search_fwd_s    : slow forward creep to advance position

        At search_turn_spd=0.40 rad/s, search_arm_s=0.8 s → ±18° per arm.
        Call reset_pid() on line re-acquisition to restart sweep state.
        """
        if self._search_phase_t == 0.0:
            self._search_phase   = 0
            self._search_phase_t = now

        durations = (
            self._search_arm_s,
            self._search_arm_s * 2.0,
            self._search_arm_s,
            self._search_fwd_s,
        )
        if now - self._search_phase_t >= durations[self._search_phase]:
            self._search_phase   = (self._search_phase + 1) % 4
            self._search_phase_t = now

        if self._search_phase == 0:
            return 0.0, +self._search_turn_spd
        elif self._search_phase == 1:
            return 0.0, -self._search_turn_spd
        elif self._search_phase == 2:
            return 0.0, +self._search_turn_spd
        else:
            return self._linear_speed * self._lost_lin_frac, 0.0

    # ── Shared colour detection ──────────────────────────────────────────────
    def _compute_masks(self, roi):
        """
        Return (white_mask, yellow_mask).
        yellow_mask includes cyan range — catches yellow tape that AWB shifts to teal.
        Also detects green (outer shoulder) and blue (inner shoulder) and caches
        their centroids in _last_gcx/_last_gcy and _last_bcx.
        Stores all results for get_roi_panels().
        """
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        mw  = cv2.inRange(hsv, self._white_lo,  self._white_hi)
        my  = cv2.inRange(hsv, self._yellow_lo, self._yellow_hi)
        mc  = cv2.inRange(hsv, self._cyan_lo,   self._cyan_hi)
        mg  = cv2.inRange(hsv, self._green_lo,  self._green_hi)
        mb  = cv2.inRange(hsv, self._blue_lo,   self._blue_hi)
        self._last_mask_w = mw
        self._last_mask_y = my | mc
        self._last_mask_g = mg
        self._last_mask_b = mb
        # Compute green/blue centroids eagerly so subclasses can read them directly.
        self._last_gcx, self._last_gcy = self._color_centroid(mg)
        self._last_bcx, _              = self._color_centroid(mb)
        return mw, my | mc

    def _color_centroid(self, mask) -> Tuple[Optional[float], Optional[float]]:
        """
        Uniform-weight centroid for any single-channel mask.
        Returns (cx, cy_frac) where cy_frac is normalised 0=top 1=bottom.
        Returns (None, None) when the blob is too small.
        """
        m = cv2.erode(mask, None, iterations=1)
        m = cv2.dilate(m,   None, iterations=2)
        M = cv2.moments(m)
        if M['m00'] < self._min_area * 10:
            return None, None
        roi_h = mask.shape[0]
        cy_frac = M['m01'] / M['m00'] / roi_h if roi_h > 0 else None
        return M['m10'] / M['m00'], cy_frac

    def _yellow_centroid(self, mask) -> Optional[float]:
        """Uniform-weight centroid for yellow — computes both x and y positions."""
        cx, cy = self._color_centroid(mask)
        self._last_ycy = cy
        return cx
