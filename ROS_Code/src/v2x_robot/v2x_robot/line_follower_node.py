#!/usr/bin/env python3
"""
Line follower node — OpenCV HSV lane detection for vinyl road surface.

Crops the bottom portion of the camera frame, thresholds for white/yellow
lane markings, finds the largest contour centroid, and runs a PID loop to
keep the robot centered on the lane.

Topics
  Sub  /camera/image_raw       sensor_msgs/Image
  Pub  /cmd_vel_line           geometry_msgs/Twist
  Pub  /line_follower/debug    sensor_msgs/Image  (when debug_image:=true)
"""

from typing import Optional
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
import cv2
import numpy as np


class LineFollowerNode(Node):

    def __init__(self):
        super().__init__('line_follower')

        # ── Motion parameters ──────────────────────────────────────────────
        self.declare_parameter('linear_speed', 0.25)       # m/s straight-line speed
        self.declare_parameter('max_angular_speed', 1.2)   # rad/s max turn rate
        self.declare_parameter('kp', 0.005)
        self.declare_parameter('ki', 0.0001)
        self.declare_parameter('kd', 0.002)
        self.declare_parameter('crop_top_ratio', 0.55)     # ignore top 55 % of frame
        self.declare_parameter('min_contour_area', 150)    # px² — ignore noise below this
        self.declare_parameter('debug_image', False)
        # Positive = target right of centre (robot in left lane, Indian convention)
        # Negative = target left of centre (robot in right lane, ambulance)
        self.declare_parameter('lane_offset_px', 0)

        # ── Lane colour thresholds (HSV) ───────────────────────────────────
        # White lane: any hue, low saturation, high brightness
        self.declare_parameter('white_h_low',   0)
        self.declare_parameter('white_h_high', 180)
        self.declare_parameter('white_s_low',   0)
        self.declare_parameter('white_s_high',  60)
        self.declare_parameter('white_v_low',  180)
        self.declare_parameter('white_v_high', 255)
        # Yellow lane (centre line on Indian roads)
        self.declare_parameter('yellow_h_low',  20)
        self.declare_parameter('yellow_h_high', 35)
        self.declare_parameter('yellow_s_low',  80)
        self.declare_parameter('yellow_s_high', 255)
        self.declare_parameter('yellow_v_low',  80)
        self.declare_parameter('yellow_v_high', 255)

        self._read_params()

        self._bridge = CvBridge()
        self._prev_error = 0.0
        self._integral = 0.0
        self._last_time = self.get_clock().now()
        self._last_image_time = self.get_clock().now()

        self.create_subscription(Image, '/camera/image_raw', self._image_cb, 10)
        self._cmd_pub = self.create_publisher(Twist, '/cmd_vel_line', 10)
        if self._debug:
            self._dbg_pub = self.create_publisher(Image, '/line_follower/debug', 10)

        # Publish stop if no camera frame arrives for > 1 s
        self.create_timer(0.1, self._watchdog)

        self.get_logger().info(
            f"Line follower ready  speed={self._linear_speed} m/s  "
            f"kp={self._kp} ki={self._ki} kd={self._kd}  "
            f"lane_offset={self._lane_offset:.0f}px"
        )

    # ──────────────────────────────────────────────────────────────────────
    def _read_params(self):
        p = self.get_parameter
        self._linear_speed  = p('linear_speed').value
        self._max_angular   = p('max_angular_speed').value
        self._kp            = p('kp').value
        self._ki            = p('ki').value
        self._kd            = p('kd').value
        self._crop_top      = p('crop_top_ratio').value
        self._min_area      = p('min_contour_area').value
        self._debug         = p('debug_image').value
        self._lane_offset   = float(p('lane_offset_px').value)

    # ──────────────────────────────────────────────────────────────────────
    def _image_cb(self, msg: Image):
        self._last_image_time = self.get_clock().now()

        try:
            frame = self._bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        except Exception as e:
            self.get_logger().error(f"cv_bridge: {e}", throttle_duration_sec=5.0)
            return

        h, w = frame.shape[:2]
        roi = frame[int(h * self._crop_top):, :]

        cx = self._find_centroid(roi)

        if cx is None:
            # Lost line — crawl forward so we can re-acquire
            twist = Twist()
            twist.linear.x = self._linear_speed * 0.25
            self._cmd_pub.publish(twist)
            return

        # target_x = centre + offset.  Positive offset keeps line to the right
        # (robot runs in left lane, Indian convention).
        target_x = roi.shape[1] / 2.0 + self._lane_offset
        error = cx - target_x                    # positive → line is right of target → turn right

        now = self.get_clock().now()
        dt = max((now - self._last_time).nanoseconds * 1e-9, 0.01)
        self._last_time = now

        self._integral   += error * dt
        derivative        = (error - self._prev_error) / dt
        self._prev_error  = error

        # Negative sign: positive error (line right) → negative angular (turn right in ROS)
        angular = -(self._kp * error + self._ki * self._integral + self._kd * derivative)
        angular = float(np.clip(angular, -self._max_angular, self._max_angular))

        twist = Twist()
        twist.linear.x  = self._linear_speed
        twist.angular.z = angular
        self._cmd_pub.publish(twist)

        if self._debug:
            self._publish_debug(roi, cx)

    # ──────────────────────────────────────────────────────────────────────
    def _find_centroid(self, roi) -> Optional[float]:
        """Return x-centroid of the detected lane mask, or None."""
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        p = self.get_parameter
        white_lo  = np.array([p('white_h_low').value,   p('white_s_low').value,   p('white_v_low').value])
        white_hi  = np.array([p('white_h_high').value,  p('white_s_high').value,  p('white_v_high').value])
        yellow_lo = np.array([p('yellow_h_low').value,  p('yellow_s_low').value,  p('yellow_v_low').value])
        yellow_hi = np.array([p('yellow_h_high').value, p('yellow_s_high').value, p('yellow_v_high').value])

        mask = cv2.inRange(hsv, white_lo, white_hi) | cv2.inRange(hsv, yellow_lo, yellow_hi)
        mask = cv2.erode(mask,  None, iterations=2)
        mask = cv2.dilate(mask, None, iterations=2)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        # Weighted centroid of ALL blobs above min_area.
        # This handles a broken white centre line (multiple dashes) and thin
        # yellow edge bars correctly — they all pull the centroid toward the
        # actual lane position rather than picking just one blob.
        total_m00 = 0.0
        total_m10 = 0.0
        for cnt in contours:
            if cv2.contourArea(cnt) < self._min_area:
                continue
            M = cv2.moments(cnt)
            if M['m00'] > 0:
                total_m00 += M['m00']
                total_m10 += M['m10']

        if total_m00 == 0:
            return None
        return total_m10 / total_m00

    # ──────────────────────────────────────────────────────────────────────
    def _publish_debug(self, roi, cx: float):
        dbg = roi.copy()
        h, w = dbg.shape[:2]
        target_x = int(w / 2 + self._lane_offset)
        cv2.line(dbg, (w // 2, 0),    (w // 2, h), (0, 255, 0), 1)     # green = frame centre
        cv2.line(dbg, (target_x, 0),  (target_x, h), (255, 165, 0), 1) # orange = lane target
        cv2.circle(dbg, (int(cx), h // 2), 8, (0, 0, 255), -1)         # red = detected centroid
        cv2.putText(dbg, f"err={int(cx - target_x)}", (4, 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 0), 1)
        self._dbg_pub.publish(self._bridge.cv2_to_imgmsg(dbg, encoding='bgr8'))

    # ──────────────────────────────────────────────────────────────────────
    def _watchdog(self):
        age = (self.get_clock().now() - self._last_image_time).nanoseconds * 1e-9
        if age > 1.0:
            self._cmd_pub.publish(Twist())


def main(args=None):
    rclpy.init(args=args)
    node = LineFollowerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()


if __name__ == '__main__':
    main()
