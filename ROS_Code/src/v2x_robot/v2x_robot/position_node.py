#!/usr/bin/env python3
"""
Position node — AprilTag 36h11 road-position estimator.

Tags are printed in the white centre-line gaps of the vinyl road
(replacing individual dashes), one tag every tag_spacing_m.
The existing front-facing lane-following camera sees them with no hardware change.

Zone numbers increase in the direction of travel; the position broadcaster
handles loop wrap-around when sharing with the peer robot.

Position is published at 5 Hz using the LAST SEEN tag.  Between two tags the
zone number is held constant — the distance_m value decreases as the robot
approaches the next tag.  When a tag is first seen, distance_m resets.

Topics
  Sub  /camera/image_raw  sensor_msgs/Image
  Pub  /robot/position    std_msgs/String  JSON {"zone":<int>,"distance_m":<float>}
  Pub  /position/debug    sensor_msgs/Image  (when debug_image:=true)

Parameters
  n_tags          int    Total tags in the loop             (default 16)
  tag_spacing_m   float  Physical distance between tags, m  (default 0.5)
  tag_size_m      float  Physical tag side length, m        (default 0.08)
  focal_px        float  Camera focal length in pixels      (default 250.0)
                         Calibrate: measure pixel_width of a tag at known distance,
                         then focal_px = pixel_width * known_distance / tag_size_m
  detect_every_n  int    Run detector on every Nth frame    (default 3)
  debug_image     bool   Publish annotated debug frame      (default false)
"""

import json
from typing import Optional
import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String
from cv_bridge import CvBridge


class PositionNode(Node):

    def __init__(self):
        super().__init__('position')

        self.declare_parameter('n_tags',         16)
        self.declare_parameter('tag_spacing_m',  0.5)
        self.declare_parameter('tag_size_m',     0.08)
        self.declare_parameter('focal_px',       250.0)
        self.declare_parameter('detect_every_n', 3)
        self.declare_parameter('debug_image',    False)

        p = self.get_parameter
        self._n_tags   = p('n_tags').value
        self._spacing  = p('tag_spacing_m').value
        self._tag_size = p('tag_size_m').value
        self._focal    = float(p('focal_px').value)
        self._every_n  = p('detect_every_n').value
        self._debug    = p('debug_image').value

        # AprilTag 36h11 — cv2.aruco 4.5.x compatible API
        self._aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
        try:
            # OpenCV >= 4.7
            self._aruco_params = cv2.aruco.DetectorParameters()
        except AttributeError:
            # OpenCV 4.5.x
            self._aruco_params = cv2.aruco.DetectorParameters_create()

        self._bridge    = CvBridge()
        self._frame_cnt = 0
        self._last_zone = -1    # -1 = unknown (no tag seen yet)
        self._last_dist = 0.0

        self.create_subscription(Image, '/camera/image_raw', self._image_cb, 10)
        self._pos_pub = self.create_publisher(String, '/robot/position', 10)
        if self._debug:
            self._dbg_pub = self.create_publisher(Image, '/position/debug', 10)

        # Publish last known position at 5 Hz (holds zone between tags)
        self.create_timer(0.2, self._publish_position)

        self.get_logger().info(
            f"Position node ready  n_tags={self._n_tags}  "
            f"spacing={self._spacing}m  focal={self._focal}px"
        )

    # ──────────────────────────────────────────────────────────────────────
    def _image_cb(self, msg: Image):
        self._frame_cnt += 1
        if self._frame_cnt % self._every_n != 0:
            return

        try:
            frame = self._bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        except Exception as e:
            self.get_logger().error(f"cv_bridge: {e}", throttle_duration_sec=5.0)
            return

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # cv2.aruco 4.5.x API (also works on 4.7+ in compatibility mode)
        corners, ids, _ = cv2.aruco.detectMarkers(
            gray, self._aruco_dict, parameters=self._aruco_params)

        if ids is not None and len(ids) > 0:
            # Pick tag with largest pixel area (closest, most reliable reading)
            best_idx  = 0
            best_area = 0.0
            for i, corner in enumerate(corners):
                area = float(cv2.contourArea(corner[0]))
                if area > best_area:
                    best_area = area
                    best_idx  = i

            raw_id = int(ids[best_idx][0])
            zone   = raw_id % self._n_tags          # wrap into [0, n_tags)
            pts    = corners[best_idx][0]

            # Distance estimate: pinhole model  d = focal * real_size / pixel_size
            pixel_w = float(np.linalg.norm(pts[0] - pts[1]))
            if pixel_w > 1.0:
                dist_m = (self._focal * self._tag_size) / pixel_w
                dist_m = float(np.clip(dist_m, 0.0, self._spacing))
            else:
                dist_m = 0.0

            self._last_zone = zone
            self._last_dist = dist_m
            self.get_logger().info(
                f"AprilTag id={raw_id}  zone={zone}  dist≈{dist_m:.2f}m",
                throttle_duration_sec=0.5)

            if self._debug:
                dbg = frame.copy()
                cv2.aruco.drawDetectedMarkers(dbg, corners, ids)
                cv2.putText(dbg, f"zone={zone} d={dist_m:.2f}m",
                            (4, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                self._dbg_pub.publish(self._bridge.cv2_to_imgmsg(dbg, encoding='bgr8'))

    # ──────────────────────────────────────────────────────────────────────
    def _publish_position(self):
        if self._last_zone < 0:
            return   # no tag detected yet — don't publish stale/invalid position
        msg = String()
        msg.data = json.dumps({'zone': self._last_zone,
                               'distance_m': round(self._last_dist, 3)})
        self._pos_pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = PositionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()


if __name__ == '__main__':
    main()
