#!/usr/bin/env python3
"""
Lane follower — OpenCV HSV lane detection with PID steering.

Takes a BGR camera frame and returns (vx, wz) velocity commands.
Call process(frame) at camera rate (~30 Hz); it returns the
(linear_speed, angular_speed) pair to send to the robot driver.

Tuning workflow:
  1. Run with debug=True to see the annotated window.
  2. Adjust white/yellow HSV thresholds until only road markings are lit.
  3. Adjust kp until tracking is smooth; add kd to damp oscillation.
  4. Adjust lane_offset_px if the robot consistently runs off-centre.
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
                 crop_top_ratio: float = 0.55,
                 min_contour_area: int = 150,
                 kp: float = 0.005,
                 ki: float = 0.0001,
                 kd: float = 0.002,
                 lane_offset_px: float = 0.0,
                 white_hsv_low:  Tuple = (0,   0,  190),
                 white_hsv_high: Tuple = (180, 55, 255),
                 yellow_hsv_low:  Tuple = (20,  80,  80),
                 yellow_hsv_high: Tuple = (35, 255, 255),
                 debug: bool = False):

        self._linear_speed  = linear_speed
        self._max_angular   = max_angular_speed
        self._crop_top      = crop_top_ratio
        self._min_area      = min_contour_area
        self._kp            = kp
        self._ki            = ki
        self._kd            = kd
        self._lane_offset   = float(lane_offset_px)
        self._white_lo      = np.array(white_hsv_low,  dtype=np.uint8)
        self._white_hi      = np.array(white_hsv_high, dtype=np.uint8)
        self._yellow_lo     = np.array(yellow_hsv_low, dtype=np.uint8)
        self._yellow_hi     = np.array(yellow_hsv_high, dtype=np.uint8)
        self._debug         = debug

        self._prev_error    = 0.0
        self._integral      = 0.0
        self._last_time     = time.monotonic()

        # Stream support — updated each processed frame
        self._last_roi    = None
        self._last_cx     = None
        self._last_mask_w = None   # white HSV mask (uint8 single-channel)
        self._last_mask_y = None   # yellow HSV mask

    def process(self, frame) -> Tuple[float, float]:
        """
        Process one BGR frame.  Returns (vx_m_s, wz_rad_s).
        Returns slow crawl forward (0.25×speed, 0.0) when line is lost.
        """
        h, w = frame.shape[:2]
        roi  = frame[int(h * self._crop_top):, :]
        self._last_roi = roi

        cx = self._find_centroid(roi)
        self._last_cx = cx

        if cx is None:
            if self._debug:
                self._show_debug(roi, None)
            return self._linear_speed * 0.25, 0.0

        roi_w   = roi.shape[1]
        target  = roi_w / 2.0 + self._lane_offset
        error   = cx - target      # + → centroid right of target → turn right

        now  = time.monotonic()
        dt   = max(now - self._last_time, 0.01)
        self._last_time = now

        self._integral  += error * dt
        derivative       = (error - self._prev_error) / dt
        self._prev_error = error

        angular = -(self._kp * error + self._ki * self._integral + self._kd * derivative)
        angular = float(np.clip(angular, -self._max_angular, self._max_angular))

        if self._debug:
            self._show_debug(roi, cx)

        return self._linear_speed, angular

    def reset_pid(self):
        self._integral   = 0.0
        self._prev_error = 0.0
        self._last_time  = time.monotonic()

    # ── Private ─────────────────────────────────────────────────────────────
    def _find_centroid(self, roi) -> Optional[float]:
        hsv  = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        mw   = cv2.inRange(hsv, self._white_lo,  self._white_hi)
        my   = cv2.inRange(hsv, self._yellow_lo, self._yellow_hi)
        self._last_mask_w = mw
        self._last_mask_y = my
        mask = cv2.erode(mw | my, None, iterations=2)
        mask = cv2.dilate(mask,   None, iterations=2)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        total_m00 = 0.0
        total_m10 = 0.0
        for cnt in contours:
            if cv2.contourArea(cnt) < self._min_area:
                continue
            M = cv2.moments(cnt)
            if M['m00'] > 0:
                total_m00 += M['m00']
                total_m10 += M['m10']

        return (total_m10 / total_m00) if total_m00 > 0 else None

    def get_roi_panels(self) -> Optional[np.ndarray]:
        """
        Return a side-by-side (640 × roi_h) BGR image for streaming:
          Left  320 px — annotated ROI (centre line / target / centroid)
          Right 320 px — HSV mask (white pixels white, yellow pixels yellow)
        Returns None until the first frame is processed.
        """
        if self._last_roi is None:
            return None

        roi = self._last_roi
        h, w = roi.shape[:2]
        target = int(w / 2 + self._lane_offset)

        # ── Left panel: lane overlay ─────────────────────────────────────
        left = roi.copy()
        cv2.line(left, (w // 2, 0), (w // 2, h), (0, 200, 0),   1)   # green  = centre
        cv2.line(left, (target,  0), (target,  h), (0, 165, 255), 1)  # orange = target
        if self._last_cx is not None:
            cv2.circle(left, (int(self._last_cx), h // 2), 6, (0, 0, 255), -1)
            err = int(self._last_cx - target)
            cv2.putText(left, f"err={err:+d}px", (2, 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 255), 1)
        else:
            cv2.putText(left, "NO LINE", (2, h // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1)
        cv2.putText(left, "LANE", (2, h - 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.3, (140, 140, 140), 1)

        # ── Right panel: coloured HSV mask ───────────────────────────────
        right = np.zeros_like(roi)
        if self._last_mask_w is not None:
            right[self._last_mask_w > 0] = (220, 220, 220)   # white → light grey
        if self._last_mask_y is not None:
            right[self._last_mask_y > 0] = (0, 215, 255)     # yellow → yellow (BGR)
        cv2.putText(right, "HSV MASK", (2, h - 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.3, (140, 140, 140), 1)

        return np.hstack([left, right])   # 640 × roi_h

    def _show_debug(self, roi, cx: Optional[float]):
        dbg = roi.copy()
        h, w = dbg.shape[:2]
        target = int(w / 2 + self._lane_offset)
        cv2.line(dbg, (w // 2, 0),   (w // 2, h), (0, 255, 0), 1)      # green = frame centre
        cv2.line(dbg, (target, 0),   (target, h),  (255, 165, 0), 1)    # orange = lane target
        if cx is not None:
            cv2.circle(dbg, (int(cx), h // 2), 8, (0, 0, 255), -1)      # red = centroid
            cv2.putText(dbg, f"err={int(cx - target)}", (4, 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 0), 1)
        cv2.imshow("lane_follower", dbg)
        cv2.waitKey(1)
