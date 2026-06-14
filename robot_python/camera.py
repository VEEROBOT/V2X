#!/usr/bin/env python3
"""
File: camera.py
Module: V2X Robot Platform — Camera Abstraction Layer

Purpose:
    Unified camera interface supporting picamera2 (Raspberry Pi Camera Module
    via libcamera) with automatic fallback to cv2.VideoCapture for development
    on a desktop/laptop. Returns BGR numpy arrays for OpenCV processing.

Author(s): Praveen Kumar
Company: Siliris Technologies Pvt. Ltd
Created: 1st March 2026
Version: 1.0

Usage:
    cam = Camera(width=320, height=240, use_picamera2=True)
    cam.start()
    frame = cam.get_frame()   # BGR numpy array (H×W×3) or None
    cam.stop()

License:
    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
    Proprietary - See LICENSE file for terms and conditions.
"""

import logging
import numpy as np

logger = logging.getLogger(__name__)

try:
    from picamera2 import Picamera2
    _HAS_PICAMERA2 = True
except ImportError:
    _HAS_PICAMERA2 = False


class Camera:

    def __init__(self, device: int = 0, width: int = 320, height: int = 240,
                 use_picamera2: bool = True):
        self._device     = device
        self._width      = width
        self._height     = height
        self._use_picam2 = use_picamera2 and _HAS_PICAMERA2
        self._picam      = None
        self._cap        = None

        if use_picamera2 and not _HAS_PICAMERA2:
            logger.warning(
                "picamera2 requested but not installed — falling back to cv2.VideoCapture.\n"
                "  Install: sudo apt install python3-picamera2"
            )

    def start(self) -> bool:
        if self._use_picam2:
            return self._start_picamera2()
        return self._start_opencv()

    def stop(self):
        if self._picam:
            try:
                self._picam.stop()
                self._picam.close()
            except Exception:
                pass
            self._picam = None
        if self._cap:
            self._cap.release()
            self._cap = None

    def get_frame(self):
        """Return BGR numpy array or None."""
        if self._picam:
            return self._grab_picamera2()
        if self._cap:
            return self._grab_opencv()
        return None

    def is_open(self) -> bool:
        if self._picam:
            return True
        if self._cap:
            return self._cap.isOpened()
        return False

    # ── picamera2 path ───────────────────────────────────────────────────
    def _start_picamera2(self) -> bool:
        try:
            self._picam = Picamera2()
            cfg = self._picam.create_video_configuration(
                main={"size": (self._width, self._height), "format": "BGR888"}
            )
            self._picam.configure(cfg)
            self._picam.start()
            logger.info("Camera: picamera2  %dx%d", self._width, self._height)
            return True
        except Exception as e:
            logger.error("picamera2 failed (%s) — trying cv2.VideoCapture", e)
            self._picam = None
            return self._start_opencv()

    def _grab_picamera2(self):
        try:
            return self._picam.capture_array()   # BGR888 → H×W×3 numpy
        except Exception as e:
            logger.error("picamera2 capture error: %s", e)
            return None

    # ── cv2 fallback path ────────────────────────────────────────────────
    def _start_opencv(self) -> bool:
        import cv2
        self._cap = cv2.VideoCapture(self._device)
        if not self._cap.isOpened():
            logger.error("cv2.VideoCapture(%d) failed", self._device)
            return False
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        logger.info("Camera: cv2.VideoCapture(%d)  %dx%d",
                    self._device, self._width, self._height)
        return True

    def _grab_opencv(self):
        ok, frame = self._cap.read()
        return frame if ok else None
