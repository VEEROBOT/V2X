#!/usr/bin/env python3
"""
Lane follower factory.

Usage in main_car.py:
    from algorithms import create_follower
    follower = create_follower(cfg['lane_follower'], debug=True)

To add a new algorithm:
    1. Create algorithms/my_algo.py with a class that extends BaseFollower.
    2. Import it below and add a branch in create_follower().
    3. Set  lane_follower.algorithm: my_algo  in config.yaml.
"""

from .centroid       import CentroidFollower
from .pure_pursuit   import PurePursuitFollower
from .recorded_path  import RecordedPathFollower


def create_follower(lc: dict, debug: bool = False):
    """Build the lane follower selected by lc['algorithm']."""
    algo = lc.get('algorithm', 'pure_pursuit').lower()

    common = dict(
        linear_speed      = lc['linear_speed'],
        max_angular_speed = lc['max_angular_speed'],
        crop_top_ratio    = lc['crop_top_ratio'],
        min_contour_area  = lc['min_contour_area'],
        lane_offset_px    = lc['lane_offset_px'],
        white_hsv_low     = (lc['white_h_low'],  lc['white_s_low'],  lc['white_v_low']),
        white_hsv_high    = (lc['white_h_high'], lc['white_s_high'], lc['white_v_high']),
        yellow_hsv_low    = (lc['yellow_h_low'],  lc['yellow_s_low'],  lc['yellow_v_low']),
        yellow_hsv_high   = (lc['yellow_h_high'], lc['yellow_s_high'], lc['yellow_v_high']),
        cyan_hsv_low      = (lc['cyan_h_low'],  lc['cyan_s_low'],  lc['cyan_v_low']),
        cyan_hsv_high     = (lc['cyan_h_high'], lc['cyan_s_high'], lc['cyan_v_high']),
        yellow_repel_frac = lc.get('yellow_repel_frac', 0.65),
        lost_linear_frac  = lc.get('lost_linear_frac',  0.50),
        lost_stop_s       = lc.get('lost_stop_s',        4.0),
        no_white_stop_s   = lc.get('no_white_stop_s',    8.0),
        debug             = debug,
    )

    pp_params = dict(
        kpp            = lc.get('kpp', 50.0),
        lookahead_frac = lc.get('lookahead_frac', 0.50),
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
