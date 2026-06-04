#!/usr/bin/env python3
"""
Lyra Wheel Odometry Node
WHEEL-ONLY, NO TF (EKF IS TF AUTHORITY)
"""

import math
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy

from std_msgs.msg import Int32MultiArray
from nav_msgs.msg import Odometry
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue


class LyraWheelOdomNode(Node):
    def __init__(self):
        super().__init__('lyra_wheel_odometry')

        # Parameters
        self.declare_parameter('wheel_diameter_m', 0.13)
        self.declare_parameter('track_width_m', 0.377)
        self.declare_parameter('ticks_per_rev', 3600)

        self.wheel_diameter = float(self.get_parameter('wheel_diameter_m').value)
        self.track_width = float(self.get_parameter('track_width_m').value)
        self.ticks_per_rev = int(self.get_parameter('ticks_per_rev').value)

        self.meters_per_tick = (math.pi * self.wheel_diameter) / self.ticks_per_rev

        # Timing limits
        self.min_dt = 0.005   # 5 ms
        self.max_dt = 0.5

        self.sensor_timeout = 0.5
        self.last_msg_time = None

        self.get_logger().info(
            f'Wheel odometry | D={self.wheel_diameter} W={self.track_width} m/tick={self.meters_per_tick:.6f}'
        )

        # State
        self.x = 0.0
        self.y = 0.0
        self.theta = 0.0

        self.prev_ticks = None
        self.prev_time = None

        # Diagnostics
        self.update_count = 0
        self.skip_count_dt = 0
        self.skip_count_spike = 0
        self.skip_count_stale = 0

        qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)

        self.create_subscription(Int32MultiArray, '/wheel_ticks', self._ticks_cb, qos)
        self.odom_pub = self.create_publisher(Odometry, '/wheel/odom', 10)
        self.diag_pub = self.create_publisher(DiagnosticArray, '/diagnostics', 10)
        self.create_timer(1.0, self._publish_diagnostics)

    def _ticks_cb(self, msg):
        now = self.get_clock().now()

        if self.last_msg_time:
            age = (now - self.last_msg_time).nanoseconds * 1e-9
            if age > self.sensor_timeout:
                self.skip_count_stale += 1

        self.last_msg_time = now

        if len(msg.data) != 4:
            return

        if self.prev_ticks is None:
            self.prev_ticks = list(msg.data)
            self.prev_time = now
            return

        dt = (now - self.prev_time).nanoseconds * 1e-9

        if dt < self.min_dt or dt > self.max_dt:
            self.skip_count_dt += 1
            self.prev_ticks = list(msg.data)
            self.prev_time = now
            return

        fl, bl, br, fr = msg.data
        pfl, pbl, pbr, pfr = self.prev_ticks

        delta_left = ((fl - pfl) + (bl - pbl)) * 0.5
        delta_right = ((br - pbr) + (fr - pfr)) * 0.5

        # ============================================================
        # SPIKE CHECK - MUST BE BEFORE POSE UPDATE!
        # ============================================================
        # Dynamic threshold based on actual dt (handles 10Hz or 20Hz)
        # Max robot speed ~1.1 m/s → max ticks/sec = 1.1 / meters_per_tick
        # MAX_SPEED_MPS gives a initial push for motors to move from zero

        MAX_SPEED_MPS = 1.8  # 1.8 m/s
        max_delta_ticks = (MAX_SPEED_MPS * dt) / self.meters_per_tick
        
        if abs(delta_left) > max_delta_ticks or abs(delta_right) > max_delta_ticks:
            self.skip_count_spike += 1
            self.get_logger().warn(
                f"Encoder spike: L={delta_left:.1f} R={delta_right:.1f} "
                f"(max={max_delta_ticks:.1f} for dt={dt:.3f}s) - skipping",
                throttle_duration_sec=1.0
            )
            self.prev_ticks = list(msg.data)
            self.prev_time = now
            return  # Skip this update entirely
        # ============================================================

        # NOW safe to update prev_ticks (after spike check passed)
        self.prev_ticks = list(msg.data)
        self.prev_time = now

        # Calculate distances
        dist_left = delta_left * self.meters_per_tick
        dist_right = delta_right * self.meters_per_tick

        dist_center = 0.5 * (dist_left + dist_right)
        delta_theta = (dist_right - dist_left) / self.track_width

        # Update pose (only with validated data)
        self.x += dist_center * math.cos(self.theta + delta_theta * 0.5)
        self.y += dist_center * math.sin(self.theta + delta_theta * 0.5)
        self.theta = math.atan2(math.sin(self.theta + delta_theta), math.cos(self.theta + delta_theta))

        v = dist_center / dt
        w = delta_theta / dt

        self.update_count += 1
        self._publish_odom(now, v, w)

    def _publish_odom(self, stamp, v, w):
        odom = Odometry()
        odom.header.stamp = stamp.to_msg()
        odom.header.frame_id = 'odom'
        odom.child_frame_id = 'base_footprint'

        odom.pose.pose.position.x = self.x
        odom.pose.pose.position.y = self.y
        odom.pose.pose.orientation.z = math.sin(self.theta / 2.0)
        odom.pose.pose.orientation.w = math.cos(self.theta / 2.0)

        odom.twist.twist.linear.x = v
        odom.twist.twist.angular.z = w

        # Set pose covariance
        odom.pose.covariance[0] = 0.01   # x
        odom.pose.covariance[7] = 0.01   # y
        odom.pose.covariance[35] = 0.05  # yaw

        # Set twist covariance
        odom.twist.covariance[0] = 0.01   # vx
        odom.twist.covariance[35] = 0.03  # vyaw

        self.odom_pub.publish(odom)

    def _publish_diagnostics(self):
        msg = DiagnosticArray()
        msg.header.stamp = self.get_clock().now().to_msg()

        status = DiagnosticStatus()
        status.name = 'wheel_odometry'
        status.hardware_id = 'lyra_encoders'
        status.level = DiagnosticStatus.OK
        status.message = 'OK'

        status.values.append(KeyValue(key='updates', value=str(self.update_count)))
        status.values.append(KeyValue(key='skip_dt', value=str(self.skip_count_dt)))
        status.values.append(KeyValue(key='skip_stale', value=str(self.skip_count_stale)))

        msg.status.append(status)
        self.diag_pub.publish(msg)


def main():
    rclpy.init()
    node = LyraWheelOdomNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        # rclpy.shutdown() removed - let launch system handle it


if __name__ == '__main__':
    main()
