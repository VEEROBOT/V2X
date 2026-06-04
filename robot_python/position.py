#!/usr/bin/env python3
"""
AprilTag-based road position estimator.

Call process(frame) on every Nth camera frame. The last known zone and
estimated distance are held between detections so callers can poll at
any rate without missing data.

Zone numbers increase in direction of travel (tag_id % n_tags).
distance_m is the estimated distance to the NEXT tag (decreases as
the robot approaches it).

get_position() → dict {"zone": int, "distance_m": float} or None until
the first tag is seen.
"""

import logging
from typing import Optional, Dict

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class PositionEstimator:

    def __init__(self,
                 n_tags: int = 22,
                 tag_spacing_m: float = 0.5,
                 tag_size_m: float = 0.08,
                 focal_px: float = 250.0,
                 detect_every_n: int = 3,
                 debug: bool = False):

        self._n_tags     = n_tags
        self._spacing    = tag_spacing_m
        self._tag_size   = tag_size_m
        self._focal      = float(focal_px)
        self._every_n    = detect_every_n
        self._debug      = debug

        self._frame_cnt  = 0
        self._last_zone  = -1
        self._last_dist  = 0.0

        # AprilTag 36h11 — compatible with OpenCV 4.5.x and 4.7+
        self._aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
        try:
            self._aruco_params = cv2.aruco.DetectorParameters()
        except AttributeError:
            self._aruco_params = cv2.aruco.DetectorParameters_create()

    def process(self, frame) -> None:
        """
        Process one BGR frame.  Updates internal zone/distance state.
        Call on every camera frame; detection runs every detect_every_n frames.
        """
        self._frame_cnt += 1
        if self._frame_cnt % self._every_n != 0:
            return

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = cv2.aruco.detectMarkers(
            gray, self._aruco_dict, parameters=self._aruco_params)

        if ids is None or len(ids) == 0:
            return

        # Pick largest (closest) tag
        best_idx  = 0
        best_area = 0.0
        for i, corner in enumerate(corners):
            area = float(cv2.contourArea(corner[0]))
            if area > best_area:
                best_area = area
                best_idx  = i

        raw_id  = int(ids[best_idx][0])
        zone    = raw_id % self._n_tags
        pts     = corners[best_idx][0]

        pixel_w = float(np.linalg.norm(pts[0] - pts[1]))
        if pixel_w > 1.0:
            dist_m = (self._focal * self._tag_size) / pixel_w
            dist_m = float(np.clip(dist_m, 0.0, self._spacing))
        else:
            dist_m = 0.0

        self._last_zone = zone
        self._last_dist = dist_m

        logger.debug("AprilTag id=%d  zone=%d  dist≈%.2fm", raw_id, zone, dist_m)

        if self._debug:
            dbg = frame.copy()
            cv2.aruco.drawDetectedMarkers(dbg, corners, ids)
            cv2.putText(dbg, f"zone={zone} d={dist_m:.2f}m",
                        (4, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            cv2.imshow("position", dbg)
            cv2.waitKey(1)

    def get_position(self) -> Optional[Dict]:
        """Returns {"zone": int, "distance_m": float} or None if no tag seen yet."""
        if self._last_zone < 0:
            return None
        return {'zone': self._last_zone, 'distance_m': round(self._last_dist, 3)}
