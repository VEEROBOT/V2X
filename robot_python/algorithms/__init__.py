#!/usr/bin/env python3
"""
File: __init__.py
Module: V2X Robot Platform — Lane Follower Algorithm Factory

Purpose:
    Package entry point for the algorithms module. Provides the
    create_follower() factory function that instantiates the lane-following
    algorithm selected in config.yaml (centroid, pure_pursuit, recorded_path).

Author(s): Praveen Kumar
Company: Siliris Technologies Pvt. Ltd
Created: 1st March 2026
Version: 1.0

Usage:
    from algorithms import create_follower
    follower = create_follower(cfg['lane_follower'], debug=True)

To add a new algorithm:
    1. Create algorithms/my_algo.py extending BaseFollower.
    2. Import it below and add a branch in create_follower().
    3. Set  lane_follower.algorithm: my_algo  in config.yaml.

License:
    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
    Proprietary - See LICENSE file for terms and conditions.
"""

from .centroid       import CentroidFollower
from .pure_pursuit   import PurePursuitFollower
from .recorded_path  import RecordedPathFollower


def create_follower(lc: dict, debug: bool = False):
    """Build the lane follower selected by lc['algorithm']."""
    algo = lc.get('algorithm', 'pure_pursuit').lower()

    # brightness_offset: subtract this from every V_low threshold.
    # Increase for dim rooms so dark-looking tape is still detected.
    # 0 = no adjustment (default).  Try 20–40 for dim indoor lighting.
    voff = int(lc.get('brightness_offset', 0))
    def _vlo(v): return max(0, int(v) - voff)

    common = dict(
        linear_speed       = lc['linear_speed'],
        max_angular_speed  = lc['max_angular_speed'],
        crop_top_ratio     = lc['crop_top_ratio'],
        min_contour_area   = lc['min_contour_area'],
        lane_offset_px     = lc['lane_offset_px'],
        driving_direction  = lc.get('driving_direction', 'clockwise'),
        white_hsv_low     = (lc['white_h_low'],  lc['white_s_low'],  _vlo(lc['white_v_low'])),
        white_hsv_high    = (lc['white_h_high'], lc['white_s_high'], lc['white_v_high']),
        yellow_hsv_low    = (lc['yellow_h_low'],  lc['yellow_s_low'],  _vlo(lc['yellow_v_low'])),
        yellow_hsv_high   = (lc['yellow_h_high'], lc['yellow_s_high'], lc['yellow_v_high']),
        cyan_hsv_low      = (lc['cyan_h_low'],  lc['cyan_s_low'],  _vlo(lc['cyan_v_low'])),
        cyan_hsv_high     = (lc['cyan_h_high'], lc['cyan_s_high'], lc['cyan_v_high']),
        green_hsv_low     = (lc.get('green_h_low', 40),  lc.get('green_s_low', 80),  _vlo(lc.get('green_v_low', 80))),
        green_hsv_high    = (lc.get('green_h_high', 80), lc.get('green_s_high', 255), lc.get('green_v_high', 255)),
        blue_hsv_low      = (lc.get('blue_h_low', 100),  lc.get('blue_s_low', 80),  _vlo(lc.get('blue_v_low', 80))),
        blue_hsv_high     = (lc.get('blue_h_high', 130), lc.get('blue_s_high', 255), lc.get('blue_v_high', 255)),
        yellow_repel_frac = lc.get('yellow_repel_frac', 0.65),
        green_repel_frac  = lc.get('green_repel_frac', 0.40),
        blue_repel_frac   = lc.get('blue_repel_frac', 0.40),
        lost_linear_frac     = lc.get('lost_linear_frac',      0.50),
        lost_stop_s          = lc.get('lost_stop_s',            4.0),
        no_white_stop_s      = lc.get('no_white_stop_s',        8.0),
        lost_search_delay_s  = lc.get('lost_search_delay_s',    1.5),
        lost_search_turn_spd = lc.get('lost_search_turn_spd',   0.40),
        lost_search_arm_s    = lc.get('lost_search_arm_s',      0.8),
        lost_search_fwd_s    = lc.get('lost_search_fwd_s',      0.4),
        white_v_auto         = lc.get('white_v_auto',           True),
        debug                = debug,
    )

    pp_params = dict(
        kpp            = lc.get('kpp', 50.0),
        lookahead_frac = lc.get('lookahead_frac', 0.50),
        ly_min_px      = lc.get('ly_min_px', 35.0),
        heading_kp     = lc.get('heading_kp', 0.0),
        gyro_hold_kp   = lc.get('gyro_hold_kp', 0.0),
        gyro_max_rad_s = lc.get('gyro_max_rad_s', 4.0),
    )

    if algo == 'centroid':
        return CentroidFollower(
            kp = lc.get('kp', 0.007),
            ki = lc.get('ki', 0.0),
            kd = lc.get('kd', 0.0),
            **common,
        )

    if algo == 'pure_pursuit':
        return PurePursuitFollower(**pp_params, **common)

    if algo == 'recorded_path':
        return RecordedPathFollower(
            use_training_data  = lc.get('use_training_data',  True),
            training_data_file = lc.get('training_data_file', '~/v2x_training.json'),
            ff_blend           = lc.get('ff_blend',            0.70),
            **pp_params,
            **common,
        )

    raise ValueError(f"Unknown lane follower algorithm: {algo!r}. "
                     f"Valid choices: centroid, pure_pursuit, recorded_path")
