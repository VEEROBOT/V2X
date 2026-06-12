#!/usr/bin/env python3
"""
Lane follower — HSV-based lane detection with priority steering.

Priority order each frame:
  1. White line detected  → PD controller to centre on it
  2. Yellow/cyan detected → steer AWAY (yellow is a boundary, not a target)
  3. Nothing detected     → carry last angular speed at reduced linear speed
  4. Lost > lost_stop_s   → full stop

Yellow tape often appears cyan under cool/blue AWB — the cyan HSV range
catches both so no AWB tuning is required.

Tuning workflow:
  1. Run with stream enabled and watch the HSV MASK panel.
  2. Adjust white/yellow/cyan thresholds until only the correct tape lights up.
  3. Increase kp until tracking responds, add kd to damp oscillation.
  4. Tune yellow_repel_frac — how hard the robot pushes away from yellow.
"""

import logging
import time
from typing import Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class LaneFollower:

    def __init__(self,
                 linear_speed: float = 0.20,
                 max_angular_speed: float = 1.2,
                 crop_top_ratio: float = 0.30,
                 min_contour_area: int = 150,
                 kp: float = 0.005,
                 ki: float = 0.0,
                 kd: float = 0.0,
                 lane_offset_px: float = 0.0,
                 white_hsv_low:  Tuple = (0,   0,  150),
                 white_hsv_high: Tuple = (180, 70, 255),
                 yellow_hsv_low:  Tuple = (20,  80,  80),
                 yellow_hsv_high: Tuple = (35, 255, 255),
                 cyan_hsv_low:  Tuple = (80,  80,  80),
                 cyan_hsv_high: Tuple = (100, 255, 255),
                 yellow_repel_frac: float = 0.40,
                 lost_linear_frac: float = 1.0,
                 lost_stop_s: float = 4.0,
                 no_white_stop_s: float = 8.0,
                 debug: bool = False):

        self._linear_speed   = linear_speed
        self._max_angular    = max_angular_speed
        self._crop_top       = crop_top_ratio
        self._min_area       = min_contour_area
        self._kp             = kp
        self._ki             = ki
        self._kd             = kd
        self._lane_offset    = float(lane_offset_px)
        self._white_lo       = np.array(white_hsv_low,  dtype=np.uint8)
        self._white_hi       = np.array(white_hsv_high, dtype=np.uint8)
        self._yellow_lo      = np.array(yellow_hsv_low, dtype=np.uint8)
        self._yellow_hi      = np.array(yellow_hsv_high, dtype=np.uint8)
        self._cyan_lo        = np.array(cyan_hsv_low,  dtype=np.uint8)
        self._cyan_hi        = np.array(cyan_hsv_high, dtype=np.uint8)
        self._repel_frac      = float(yellow_repel_frac)
        self._lost_lin_frac   = float(lost_linear_frac)
        self._lost_stop_s     = float(lost_stop_s)
        self._no_white_stop_s = float(no_white_stop_s)
        self._debug           = debug

        self._prev_error   = 0.0
        self._integral     = 0.0
        self._last_time    = time.monotonic()
        self._last_wz      = 0.0    # last angular output — carried during line loss
        self._lost_start   = None   # monotonic timestamp when pure LOST began
        self._no_white_start = None # monotonic timestamp when white was last seen
        self._mode         = 'INIT' # WHITE / YELLOW / LOST — for display

        # Stream support — set every frame
        self._last_roi    = None
        self._last_cx     = None   # white centroid x (None when not on white)
        self._last_ycx    = None   # yellow centroid x (None when not on yellow)
        self._last_mask_w = None
        self._last_mask_y = None

    # ── Public API ───────────────────────────────────────────────────────────
    def process(self, frame) -> Tuple[float, float]:
        """
        Process one BGR frame.  Returns (vx_m_s, wz_rad_s).
        """
        h, w = frame.shape[:2]
        roi  = frame[int(h * self._crop_top):, :]
        self._last_roi = roi

        white_cx, yellow_cx = self._find_line_positions(roi)
        self._last_cx  = white_cx
        self._last_ycx = yellow_cx

        roi_w  = roi.shape[1]
        target = roi_w / 2.0 + self._lane_offset
        now    = time.monotonic()

        # Track continuous time without white — spans YELLOW and LOST together.
        # Prevents infinite bouncing between two yellow boundaries with no escape.
        if white_cx is None:
            if self._no_white_start is None:
                self._no_white_start = now
        else:
            self._no_white_start = None

        no_white_s = (now - self._no_white_start) if self._no_white_start is not None else 0.0
        if no_white_s >= self._no_white_stop_s:
            self._mode = 'LOST'
            return 0.0, 0.0

        # ── Priority 1: white line found — follow it ─────────────────────────
        if white_cx is not None:
            error = white_cx - target

            # First frame back on white after LOST/YELLOW/INIT — reset derivative
            # state so the gap in time doesn't cause a huge wz spike.
            if self._mode != 'WHITE':
                self._prev_error = error
                self._integral   = 0.0
                self._last_time  = now

            self._lost_start = None
            self._mode = 'WHITE'

            dt    = max(now - self._last_time, 0.01)
            self._last_time = now

            self._integral  += error * dt
            derivative       = (error - self._prev_error) / dt
            self._prev_error = error

            wz = -(self._kp * error + self._ki * self._integral + self._kd * derivative)
            wz = float(np.clip(wz, -self._max_angular, self._max_angular))
            self._last_wz = wz

            # Slow down proportionally when far off-centre — prevents overshoot ping-pong.
            # At err=0px: full speed. At err≥120px: 30% speed.
            err_ratio = min(abs(error) / 120.0, 1.0)
            vx_cmd = self._linear_speed * (1.0 - 0.70 * err_ratio)

            if self._debug:
                self._show_debug(roi, white_cx)
            return vx_cmd, wz

        # ── Priority 2: yellow/cyan boundary — repel away from it ───────────
        if yellow_cx is not None:
            self._lost_start = None
            self._mode = 'YELLOW'
            self._prev_error = 0.0
            self._integral   = 0.0

            # yellow right of centre → steer left (+wz away); left → steer right (−wz away)
            wz = float(np.sign(yellow_cx - target) * self._max_angular * self._repel_frac)
            wz = float(np.clip(wz, -self._max_angular, self._max_angular))
            self._last_wz = wz

            if self._debug:
                self._show_debug(roi, None)
            return self._linear_speed * 0.5, wz

        # ── Priority 3: nothing — carry last angular velocity ────────────────
        if self._lost_start is None:
            self._lost_start = now
        lost_s = now - self._lost_start
        self._mode = 'LOST'

        if self._debug:
            self._show_debug(roi, None)

        if lost_s >= self._lost_stop_s:
            return 0.0, 0.0

        return self._linear_speed * self._lost_lin_frac, self._last_wz

    def reset_pid(self):
        self._integral   = 0.0
        self._prev_error = 0.0
        self._last_time  = time.monotonic()
        self._lost_start = None
        self._last_wz    = 0.0

    def get_mode(self) -> str:
        return self._mode

    def get_debug_info(self) -> dict:
        """Returns a snapshot of current detection state for logging."""
        roi_w  = self._last_roi.shape[1] if self._last_roi is not None else 320
        target = roi_w / 2.0 + self._lane_offset
        white_err = int(self._last_cx - target) if self._last_cx is not None else None
        return {
            'mode':      self._mode,
            'white_err': white_err,
            'last_wz':   round(self._last_wz, 3),
        }

    # ── Private ──────────────────────────────────────────────────────────────
    def _find_line_positions(self, roi) -> Tuple[Optional[float], Optional[float]]:
        """Return (white_cx, yellow_cx).  Each is None if not detected."""
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        mw = cv2.inRange(hsv, self._white_lo,  self._white_hi)
        my = cv2.inRange(hsv, self._yellow_lo, self._yellow_hi)
        mc = cv2.inRange(hsv, self._cyan_lo,   self._cyan_hi)

        self._last_mask_w = mw
        self._last_mask_y = my | mc

        white_cx  = self._centroid_x(mw)
        yellow_cx = self._centroid_x(my | mc)
        return white_cx, yellow_cx

    def _centroid_x(self, mask) -> Optional[float]:
        m = cv2.erode(mask, None, iterations=1)
        m = cv2.dilate(m,   None, iterations=2)

        contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        valid = [cnt for cnt in contours if cv2.contourArea(cnt) >= self._min_area]
        if not valid:
            return None

        # Bottom-weighted centroid: near (bottom) rows count 4× more than far (top)
        # rows. On a curve the near portion already shows the bend; without weighting
        # the far straight section pulls the centroid back toward centre, making the
        # curve look milder than it is and causing the robot to under-steer.
        h, w = m.shape
        clean = np.zeros_like(m)
        cv2.drawContours(clean, valid, -1, 255, -1)

        row_w  = np.linspace(0.25, 1.0, h, dtype=np.float64).reshape(-1, 1)
        wgt    = clean.astype(np.float64) * row_w
        m00    = wgt.sum()
        if m00 == 0:
            return None
        col_idx = np.arange(w, dtype=np.float64).reshape(1, -1)
        return (wgt * col_idx).sum() / m00

    def get_roi_panels(self) -> Optional[np.ndarray]:
        """
        Return a side-by-side BGR image for streaming:
          Left  — annotated ROI (centre / target / white centroid / yellow centroid)
          Right — HSV mask (white = light grey, yellow/cyan = yellow)
        """
        if self._last_roi is None:
            return None

        roi = self._last_roi
        h, w = roi.shape[:2]
        target = int(w / 2 + self._lane_offset)

        # ── Left panel ───────────────────────────────────────────────────────
        left = roi.copy()
        cv2.line(left, (w // 2, 0), (w // 2, h), (0, 200, 0),   1)  # green  = centre
        cv2.line(left, (target,  0), (target,  h), (0, 165, 255), 1) # orange = target

        if self._last_cx is not None:
            cx = int(self._last_cx)
            cv2.circle(left, (cx, h // 2), 6, (0, 0, 255), -1)       # red = white centroid
            err = int(self._last_cx - target)
            cv2.putText(left, f"err={err:+d}px", (2, 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 255), 1)

        if self._last_ycx is not None:
            yx = int(self._last_ycx)
            cv2.circle(left, (yx, h * 3 // 4), 6, (0, 215, 255), -1)  # yellow = yellow centroid

        mode_col = {
            'WHITE':  (0, 255, 0),
            'YELLOW': (0, 215, 255),
            'LOST':   (0, 0, 255),
            'INIT':   (128, 128, 128),
        }.get(self._mode, (128, 128, 128))
        cv2.putText(left, self._mode, (2, h - 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, mode_col, 1)

        # ── Right panel: coloured HSV mask ───────────────────────────────────
        right = np.zeros_like(roi)
        if self._last_mask_w is not None:
            right[self._last_mask_w > 0] = (220, 220, 220)   # white → light grey
        if self._last_mask_y is not None:
            right[self._last_mask_y > 0] = (0, 215, 255)     # yellow/cyan → yellow
        cv2.putText(right, "HSV MASK", (2, h - 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.3, (140, 140, 140), 1)

        return np.hstack([left, right])

    def _show_debug(self, roi, cx: Optional[float]):
        dbg = roi.copy()
        h, w = dbg.shape[:2]
        target = int(w / 2 + self._lane_offset)
        cv2.line(dbg, (w // 2, 0), (w // 2, h), (0, 255, 0), 1)
        cv2.line(dbg, (target, 0), (target, h),  (255, 165, 0), 1)
        if cx is not None:
            cv2.circle(dbg, (int(cx), h // 2), 8, (0, 0, 255), -1)
            cv2.putText(dbg, f"err={int(cx - target)}", (4, 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 0), 1)
        cv2.imshow("lane_follower", dbg)
        cv2.waitKey(1)
