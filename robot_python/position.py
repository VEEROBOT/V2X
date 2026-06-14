#!/usr/bin/env python3
"""
File: position.py
Module: V2X Robot Platform — AprilTag Position Estimator

Purpose:
    Estimates the robot's zone on the oval track by detecting AprilTag markers
    via the downward-facing camera. Inner-track tags (IDs 0…n_inner_tags-1)
    define the current zone; outer-track tags flag an off-track condition while
    preserving the last known inner zone for recovery. Zone information is
    broadcast over UDP so the car can determine if the ambulance is behind it.

Author(s): Praveen Kumar
Company: Siliris Technologies Pvt. Ltd
Created: 1st March 2026
Version: 1.0

Arena Layout:
    10 inner tags — white oval boundary, spaced ~0.61 m apart
     8 outer tags — yellow race boundary (recovery / off-track detection only)

License:
    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
    Proprietary - See LICENSE file for terms and conditions.
"""

import logging
from typing import Optional, Dict

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class PositionEstimator:

    def __init__(self,
                 n_inner_tags: int = 10,
                 n_outer_tags: int = 8,
                 tag_spacing_m: float = 0.61,
                 tag_size_m: float = 0.08,
                 focal_px: float = 250.0,
                 detect_every_n: int = 3,
                 debug: bool = False):

        self._n_inner    = n_inner_tags
        self._n_outer    = n_outer_tags
        self._n_tags     = n_inner_tags   # used by EmergencyHandler via get_position
        self._spacing    = tag_spacing_m
        self._tag_size   = tag_size_m
        self._focal      = float(focal_px)
        self._every_n    = detect_every_n
        self._debug      = debug

        self._frame_cnt     = 0
        self._last_zone     = -1
        self._last_dist     = 0.0
        self._off_track     = False
        self._last_corners  = []   # all corners from last detection frame
        self._last_ids      = []   # matching IDs

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
            self._last_corners = []
            self._last_ids     = []
            return

        self._last_corners = corners
        self._last_ids     = [int(i[0]) for i in ids]

        # Pick largest (closest) tag
        best_idx  = 0
        best_area = 0.0
        for i, corner in enumerate(corners):
            area = float(cv2.contourArea(corner[0]))
            if area > best_area:
                best_area = area
                best_idx  = i

        raw_id  = int(ids[best_idx][0])
        pts     = corners[best_idx][0]

        pixel_w = float(np.linalg.norm(pts[0] - pts[1]))
        dist_m  = (self._focal * self._tag_size) / pixel_w if pixel_w > 1.0 else 0.0
        dist_m  = float(np.clip(dist_m, 0.0, self._spacing))

        if raw_id < self._n_inner:
            # Primary inner-oval tag — updates zone and clears off-track flag
            self._last_zone = raw_id
            self._last_dist = dist_m
            self._off_track = False
            logger.debug("Inner tag id=%d  zone=%d  dist≈%.2fm", raw_id, raw_id, dist_m)
        elif raw_id < self._n_inner + self._n_outer:
            # Outer reference tag — robot has drifted off the inner oval
            if not self._off_track:
                logger.warning("Outer reference tag id=%d — robot off inner track", raw_id)
            self._off_track = True
        else:
            logger.debug("Unknown tag id=%d — ignored", raw_id)

        if self._debug:
            dbg = frame.copy()
            cv2.aruco.drawDetectedMarkers(dbg, corners, ids)
            label = f"zone={self._last_zone} d={self._last_dist:.2f}m" + (" [OFF]" if self._off_track else "")
            cv2.putText(dbg, label, (4, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            cv2.imshow("position", dbg)
            cv2.waitKey(1)

    def get_position(self) -> Optional[Dict]:
        """Returns {"zone": int, "distance_m": float, "off_track": bool} or None if no inner tag seen yet."""
        if self._last_zone < 0:
            return None
        return {
            'zone':       self._last_zone,
            'distance_m': round(self._last_dist, 3),
            'off_track':  self._off_track,
        }

    def is_off_track(self) -> bool:
        """True when the last detected tag was an outer reference tag."""
        return self._off_track

    def get_last_detections(self):
        """Returns (corners_list, ids_list) from the most recent detection frame."""
        return self._last_corners, self._last_ids
