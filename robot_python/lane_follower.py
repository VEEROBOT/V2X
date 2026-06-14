#!/usr/bin/env python3
"""
File: lane_follower.py
Module: V2X Robot Platform — Lane Follower Backward-Compatibility Shim

Purpose:
    Backward-compatibility import shim. New code should use create_follower()
    from the algorithms package instead of importing LaneFollower directly.

Author(s): Praveen Kumar
Company: Siliris Technologies Pvt. Ltd
Created: 1st March 2026
Version: 1.0

License:
    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
    Proprietary - See LICENSE file for terms and conditions.
"""
# New code should use:  from algorithms import create_follower
from algorithms.centroid import CentroidFollower as LaneFollower  # noqa: F401
