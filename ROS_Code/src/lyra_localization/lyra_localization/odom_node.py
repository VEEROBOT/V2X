#!/usr/bin/env python3
"""
Lyra Odometry Node (Phase 2)

Computes dead-reckoning odometry from wheel encoder ticks.

Publishes:
- /odom  (nav_msgs/Odometry)
- TF: odom → base_link

ASSUMPTIONS (frozen in README):
- wheel_ticks order = [FL, BL, BR, FR]
- ticks are absolute, polarity-corrected, wheel-space
- skid-steer / differential drive
"""

import math
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy

from std_msgs.msg import Int32MultiArray
from nav_msgs.msg import Odometry
from geometry_msgs.msg import TransformStamped
import tf2_ros


class LyraOdomNode(Node):
    def __init__(self):
        super().__init__('lyra_odometry')

        # --------------------------------------------------
        # Parameters (MUST match STM + README)
        # --------------------------------------------------
        self.declare_parameter('wheel_diameter_m', 0.13)
        self.declare_parameter('track_width_m', 0.377)
        self.declare_parameter('ticks_per_rev', 3600)

        self.wheel_diameter = self.get_parameter('wheel_diameter_m').value
        self.track_width = self.get_parameter('track_width_m').value
        self.ticks_per_rev = self.get_parameter('ticks_per_rev').value

        self.meters_per_tick = (
            math.pi * self.wheel_diameter
        ) / self.ticks_per_rev

        self.get_logger().info(
            f'Odom params: wheel_diameter={self.wheel_diameter}m, '
            f'track_width={self.track_width}m, '
            f'meters_per_tick={self.meters_per_tick:.6f}'
        )

        # --------------------------------------------------
        # State
        # --------------------------------------------------
        self.x = 0.0
        self.y = 0.0
        self.theta = 0.0

        self.prev_ticks = None
        self.prev_time = None

        # --------------------------------------------------
        # ROS interfaces
        # --------------------------------------------------
        qos = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.BEST_EFFORT
        )

        self.create_subscription(
            Int32MultiArray,
            '/wheel_ticks',
            self._ticks_cb,
            qos
        )

        self.odom_pub = self.create_publisher(Odometry, '/odom', 10)
        self.tf_broadcaster = tf2_ros.TransformBroadcaster(self)

        self.get_logger().info('Lyra odometry node started')

    # ==================================================
    # Encoder callback
    # ==================================================
    def _ticks_cb(self, msg: Int32MultiArray):
        now = self.get_clock().now()

        if len(msg.data) != 4:
            self.get_logger().warn(
                'wheel_ticks must have 4 elements [FL, BL, BR, FR]',
                throttle_duration_sec=5.0
            )
            return

        if self.prev_ticks is None:
            self.prev_ticks = list(msg.data)
            self.prev_time = now
            return

        dt = (now - self.prev_time).nanoseconds * 1e-9
        if dt <= 0.0:
            return

        # Order: [FL, BL, BR, FR]
        fl, bl, br, fr = msg.data
        pfl, pbl, pbr, pfr = self.prev_ticks

        delta_left = ((fl - pfl) + (bl - pbl)) * 0.5
        delta_right = ((br - pbr) + (fr - pfr)) * 0.5

        self.prev_ticks = list(msg.data)
        self.prev_time = now

        # --------------------------------------------------
        # Distance + rotation
        # --------------------------------------------------
        dist_left = delta_left * self.meters_per_tick
        dist_right = delta_right * self.meters_per_tick

        dist_center = 0.5 * (dist_left + dist_right)
        delta_theta = (dist_right - dist_left) / self.track_width

        # Midpoint integration (IMPORTANT)
        self.x += dist_center * math.cos(self.theta + delta_theta * 0.5)
        self.y += dist_center * math.sin(self.theta + delta_theta * 0.5)
        self.theta += delta_theta

        self.theta = math.atan2(math.sin(self.theta), math.cos(self.theta))

        v = dist_center / dt
        w = delta_theta / dt

        self._publish_odom(now, v, w)
        self._publish_tf(now)

    # ==================================================
    # Publishing
    # ==================================================
    def _publish_odom(self, stamp, v, w):
        odom = Odometry()
        odom.header.stamp = stamp.to_msg()
        odom.header.frame_id = 'odom'
        odom.child_frame_id = 'base_link'

        odom.pose.pose.position.x = self.x
        odom.pose.pose.position.y = self.y

        odom.pose.pose.orientation.z = math.sin(self.theta * 0.5)
        odom.pose.pose.orientation.w = math.cos(self.theta * 0.5)

        # Nav2-friendly conservative covariance
        odom.pose.covariance = [
            0.05, 0, 0, 0, 0, 0,
            0, 0.05, 0, 0, 0, 0,
            0, 0, 1e6, 0, 0, 0,
            0, 0, 0, 1e6, 0, 0,
            0, 0, 0, 0, 1e6, 0,
            0, 0, 0, 0, 0, 0.1
        ]

        odom.twist.twist.linear.x = v
        odom.twist.twist.angular.z = w

        self.odom_pub.publish(odom)

    def _publish_tf(self, stamp):
        t = TransformStamped()
        t.header.stamp = stamp.to_msg()
        t.header.frame_id = 'odom'
        t.child_frame_id = 'base_link'

        t.transform.translation.x = self.x
        t.transform.translation.y = self.y

        t.transform.rotation.z = math.sin(self.theta * 0.5)
        t.transform.rotation.w = math.cos(self.theta * 0.5)

        self.tf_broadcaster.sendTransform(t)


def main():
    rclpy.init()
    node = LyraOdomNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        # rclpy.shutdown() removed - let launch system handle it


if __name__ == '__main__':
    main()
