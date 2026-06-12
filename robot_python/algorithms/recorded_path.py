#!/usr/bin/env python3
"""
Recorded Path lane follower — Learning from Demonstration.

Training phase (press X button while driving manually one full loop):
  Records the commanded curvature (wz/vx) per AprilTag zone.  Each zone
  is a fixed segment of the track, so 10 numbers capture where the track
  turns and by how much.

Replay phase (autonomous mode):
  Blends a feedforward term from the training data with the live Pure
  Pursuit camera output:

      wz = wz_ff * ff_blend  +  wz_camera * (1 − ff_blend)

  ff_blend = 0 → pure camera (same as pure_pursuit)
  ff_blend = 1 → pure training data (ignores camera)
  ff_blend = 0.7 → recommended starting point

Why this helps:
  The camera can struggle on curves (delayed reaction, centroid lag).
  The training data knows the curve is coming and pre-steers, while the
  camera provides the fine error correction.

Disabling:
  Set  use_training_data: false  in config.yaml — feedforward is ignored
  entirely and the algorithm degrades gracefully to pure pursuit.

Training file:  ~/v2x_training.json  (auto-saved, survives reboots)
"""

import json
import logging
import os
from typing import Optional

import numpy as np

from .pure_pursuit import PurePursuitFollower

logger = logging.getLogger(__name__)


class RecordedPathFollower(PurePursuitFollower):
    """Extends PurePursuitFollower with a zone-keyed feedforward layer."""

    def __init__(self, *,
                 use_training_data: bool  = True,
                 training_data_file: str  = '~/v2x_training.json',
                 ff_blend:           float = 0.70,
                 **kwargs):
        super().__init__(**kwargs)
        self._use_training  = use_training_data
        self._data_file     = os.path.expanduser(training_data_file)
        self._ff_blend      = float(ff_blend)

        # Per-zone curvature learned from training  {zone_int: curvature_float}
        self._trained_curvature: dict = {}

        # Training accumulator  {zone_int: {'curv_sum', 'vx_sum', 'count'}}
        self._raw_data: dict = {}
        self._recording = False

        self._load_data()

    # ── Public API ───────────────────────────────────────────────────────────
    def process(self, frame):
        # Run the full pure-pursuit camera pipeline (inherits everything)
        vx_cam, wz_cam = super().process(frame)

        if not self._use_training or not self._trained_curvature:
            return vx_cam, wz_cam

        # Only apply feedforward when actively tracking white — not during
        # LOST or YELLOW where the camera output is already a fallback.
        if self._mode not in ('WHITE',):
            return vx_cam, wz_cam

        curvature_ff = self._trained_curvature.get(self._current_zone)
        if curvature_ff is None:
            return vx_cam, wz_cam   # no training data for this zone → camera only

        wz_ff    = curvature_ff * vx_cam   # scale with current speed
        wz_blend = wz_ff * self._ff_blend + wz_cam * (1.0 - self._ff_blend)
        wz_blend = float(np.clip(wz_blend, -self._max_angular, self._max_angular))
        return vx_cam, wz_blend

    def toggle_training(self):
        """Call when X button pressed.  Starts or stops the training session."""
        if self._recording:
            self._finalize_training()
            self._recording = False
        else:
            self._raw_data  = {}
            self._recording = True
            logger.info("Training STARTED — drive one full loop then press X again")

    def is_recording(self) -> bool:
        return self._recording

    def record(self, vx: float, wz: float, zone: int):
        """
        Accumulate one manual-drive sample into the training buffer.
        Called by main_car for every iteration where the joystick is active
        and training is in progress.
        """
        if not self._recording or zone < 0 or abs(vx) < 0.02:
            return
        curvature = wz / vx
        if zone not in self._raw_data:
            self._raw_data[zone] = {'curv_sum': 0.0, 'vx_sum': 0.0, 'count': 0}
        d = self._raw_data[zone]
        d['curv_sum'] += curvature
        d['vx_sum']   += vx
        d['count']    += 1

    def get_debug_info(self) -> dict:
        info = super().get_debug_info()
        info['recording'] = self._recording
        info['ff_zones']  = len(self._trained_curvature)
        return info

    # ── Private ──────────────────────────────────────────────────────────────
    def _finalize_training(self):
        processed = {}
        for zone, d in self._raw_data.items():
            if d['count'] < 3:   # need at least 3 samples to trust the zone
                continue
            processed[str(zone)] = {
                'curvature_mean': round(d['curv_sum'] / d['count'], 4),
                'vx_mean':        round(d['vx_sum']   / d['count'], 4),
                'count':          d['count'],
            }
        try:
            with open(self._data_file, 'w') as f:
                json.dump({'version': 1, 'zones': processed}, f, indent=2)
            logger.info("Training saved → %s  (%d zones)", self._data_file, len(processed))
        except OSError as e:
            logger.error("Could not save training data: %s", e)
        self._load_data()

    def _load_data(self):
        if not os.path.exists(self._data_file):
            logger.info("No training data file at %s — feedforward disabled until trained",
                        self._data_file)
            return
        try:
            with open(self._data_file) as f:
                data = json.load(f)
            self._trained_curvature = {
                int(k): v['curvature_mean']
                for k, v in data.get('zones', {}).items()
            }
            logger.info("Loaded training data: %d zones from %s",
                        len(self._trained_curvature), self._data_file)
        except Exception as e:
            logger.error("Failed to load training data: %s", e)
