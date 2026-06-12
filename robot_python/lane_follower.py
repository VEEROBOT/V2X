#!/usr/bin/env python3
# Backward-compatibility shim.
# New code should use:  from algorithms import create_follower
from algorithms.centroid import CentroidFollower as LaneFollower  # noqa: F401
