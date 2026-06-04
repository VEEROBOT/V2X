#!/usr/bin/env python3
"""
Emergency handler node — Car robot only.

Sits between the line follower and lyra_cmd_vel_gate.  In normal operation it
passes the line-follower command straight through.  When a V2X emergency is
detected AND the ambulance is positioned BEHIND the car, the node drives
through a four-state evasion sequence:

  NORMAL → EVADING → HOLDING → RESUMING → NORMAL

Indian-road convention: ambulance approaching from behind → car moves LEFT.
Positive angular.z = counter-clockwise = left turn in ROS.

Position-aware logic (requires position_node + position_broadcaster_node):
  • NORMAL → EVADING only when ambulance is BEHIND car AND within yield_zone_gap zones.
  • HOLDING → RESUMING when ambulance zone overtakes car zone (it has passed).
  • If position is unknown (no AprilTag seen yet), falls back to V2X-only behaviour
    (yields on emergency signal alone — same as original implementation).

Topics
  Sub  /cmd_vel_line           geometry_msgs/Twist  (from line_follower_node)
       /v2x/emergency_detected std_msgs/Bool        (from v2x_bridge_node)
       /robot/position          std_msgs/String      JSON {"zone":N,"distance_m":F}
       /v2x/peer_position       std_msgs/String      JSON {"zone":N,"distance_m":F}
  Pub  /cmd_vel_nav            geometry_msgs/Twist  (into lyra_cmd_vel_gate)

Parameters
  evasion_linear_speed   float  m/s   forward speed while swerving   (default 0.12)
  evasion_angular_speed  float  rad/s left-turn rate during evasion  (default 0.9)
  evasion_duration_s     float  s     how long to steer left         (default 2.0)
  hold_timeout_s         float  s     max hold before forced resume  (default 30.0)
  clear_delay_s          float  s     grace period before resuming   (default 1.0)
  resume_ramp_duration_s float  s     speed ramp back to full        (default 2.0)
  n_tags                 int         total AprilTags in the loop     (default 16)
  yield_zone_gap         int         max zones behind to yield       (default 4)
  position_timeout_s     float  s     stale peer position timeout    (default 3.0)
"""

import json
import time
from typing import Optional

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from std_msgs.msg import Bool, String


class EmergencyHandlerNode(Node):

    _NORMAL   = 'NORMAL'
    _EVADING  = 'EVADING'
    _HOLDING  = 'HOLDING'
    _RESUMING = 'RESUMING'

    def __init__(self):
        super().__init__('emergency_handler')

        # ── Parameters ─────────────────────────────────────────────────────
        self.declare_parameter('evasion_linear_speed',   0.12)
        self.declare_parameter('evasion_angular_speed',  0.9)
        self.declare_parameter('evasion_duration_s',     2.0)
        self.declare_parameter('hold_timeout_s',        30.0)
        self.declare_parameter('clear_delay_s',          1.0)
        self.declare_parameter('resume_ramp_duration_s', 2.0)
        self.declare_parameter('n_tags',                16)
        self.declare_parameter('yield_zone_gap',         4)    # 4 zones × 0.5m = 2m
        self.declare_parameter('position_timeout_s',     3.0)  # stale after 3s

        p = self.get_parameter
        self._ev_linear    = p('evasion_linear_speed').value
        self._ev_angular   = p('evasion_angular_speed').value
        self._ev_dur       = p('evasion_duration_s').value
        self._hold_max     = p('hold_timeout_s').value
        self._clear_delay  = p('clear_delay_s').value
        self._ramp_dur     = p('resume_ramp_duration_s').value
        self._n_tags       = p('n_tags').value
        self._yield_gap    = p('yield_zone_gap').value
        self._pos_timeout  = p('position_timeout_s').value

        # ── State ──────────────────────────────────────────────────────────
        self._state            = self._NORMAL
        self._state_enter_time = time.monotonic()
        self._emergency_active = False
        self._last_line_cmd    = Twist()

        # Position state
        self._own_zone         = -1     # -1 = unknown
        self._amb_zone         = -1
        self._amb_last_time    = 0.0    # monotonic time of last peer position update

        # Holding-state timers
        self._passed_stamp     = None   # when ambulance overtook us
        self._clear_stamp      = None   # when V2X emergency signal went False

        # ── ROS I/O ────────────────────────────────────────────────────────
        self.create_subscription(Twist,  '/cmd_vel_line',           self._line_cb,      10)
        self.create_subscription(Bool,   '/v2x/emergency_detected', self._emergency_cb, 10)
        self.create_subscription(String, '/robot/position',         self._own_pos_cb,   10)
        self.create_subscription(String, '/v2x/peer_position',      self._amb_pos_cb,   10)
        self._cmd_pub = self.create_publisher(Twist, '/cmd_vel_nav', 10)

        self.create_timer(0.05, self._tick)  # 20 Hz

        self.get_logger().info(
            f"Emergency handler ready  state=NORMAL  "
            f"n_tags={self._n_tags}  yield_gap={self._yield_gap} zones"
        )

    # ──────────────────────────────────────────────────────────────────────
    # Subscriptions
    # ──────────────────────────────────────────────────────────────────────
    def _line_cb(self, msg: Twist):
        self._last_line_cmd = msg

    def _emergency_cb(self, msg: Bool):
        was_active = self._emergency_active
        self._emergency_active = msg.data

        if not self._emergency_active and was_active:
            self._clear_stamp = time.monotonic()
            self.get_logger().info("V2X emergency cleared")

        if self._emergency_active and not was_active:
            self.get_logger().warn(
                f"V2X emergency detected  "
                f"own_zone={self._own_zone}  amb_zone={self._amb_zone}"
            )

    def _own_pos_cb(self, msg: String):
        try:
            data = json.loads(msg.data)
            self._own_zone = int(data.get('zone', -1))
        except (json.JSONDecodeError, ValueError):
            pass

    def _amb_pos_cb(self, msg: String):
        try:
            data = json.loads(msg.data)
            self._amb_zone      = int(data.get('zone', -1))
            self._amb_last_time = time.monotonic()
        except (json.JSONDecodeError, ValueError):
            pass

    # ──────────────────────────────────────────────────────────────────────
    # Position helpers
    # ──────────────────────────────────────────────────────────────────────
    def _position_known(self) -> bool:
        """True if both own and peer positions are fresh."""
        peer_fresh = (time.monotonic() - self._amb_last_time) < self._pos_timeout
        return (self._own_zone >= 0 and self._amb_zone >= 0 and peer_fresh)

    def _is_amb_behind(self) -> bool:
        """
        True if ambulance is BEHIND the car (considering loop wrap-around).
        Uses modular arithmetic: diff zones in [1 .. n_tags//2] = behind.
        """
        diff = (self._own_zone - self._amb_zone) % self._n_tags
        return 0 < diff <= (self._n_tags // 2)

    def _amb_gap_zones(self) -> int:
        """Number of zones between ambulance and car (shortest path around loop)."""
        diff = (self._own_zone - self._amb_zone) % self._n_tags
        return min(diff, self._n_tags - diff)

    def _should_yield(self) -> bool:
        """
        Decide whether to yield to the ambulance.
        Position-aware when possible; falls back to V2X-only when unknown.
        """
        if not self._emergency_active:
            return False
        if not self._position_known():
            # No position data — safe fallback: yield on emergency signal alone
            self.get_logger().warn(
                "Position unknown — yielding on V2X signal alone (fallback mode)",
                throttle_duration_sec=5.0)
            return True
        behind = self._is_amb_behind()
        gap    = self._amb_gap_zones()
        if behind and gap <= self._yield_gap:
            return True
        if not behind:
            self.get_logger().info(
                f"Ambulance is AHEAD (zone {self._amb_zone} vs car {self._own_zone})"
                " — NOT yielding", throttle_duration_sec=2.0)
        elif gap > self._yield_gap:
            self.get_logger().info(
                f"Ambulance {gap} zones behind (gap > {self._yield_gap}) — not yielding yet",
                throttle_duration_sec=2.0)
        return False

    # ──────────────────────────────────────────────────────────────────────
    # State machine
    # ──────────────────────────────────────────────────────────────────────
    def _enter(self, state: str):
        self._state            = state
        self._state_enter_time = time.monotonic()
        if state == self._HOLDING:
            self._passed_stamp = None
            self._clear_stamp  = None
        self.get_logger().info(f"Emergency handler → {state}")

    def _tick(self):
        now     = time.monotonic()
        elapsed = now - self._state_enter_time
        twist   = Twist()

        # ── NORMAL ──────────────────────────────────────────────────────────
        if self._state == self._NORMAL:
            twist = self._last_line_cmd
            if self._should_yield():
                self.get_logger().warn(
                    f"YIELDING — amb_zone={self._amb_zone}  "
                    f"own_zone={self._own_zone}  "
                    f"gap={self._amb_gap_zones()} zones"
                )
                self._enter(self._EVADING)

        # ── EVADING ─────────────────────────────────────────────────────────
        elif self._state == self._EVADING:
            twist.linear.x  = self._ev_linear
            twist.angular.z = self._ev_angular   # positive = left in ROS
            if elapsed >= self._ev_dur:
                self._enter(self._HOLDING)

        # ── HOLDING ─────────────────────────────────────────────────────────
        elif self._state == self._HOLDING:
            twist.linear.x  = 0.0
            twist.angular.z = 0.0

            # PRIMARY: ambulance has overtaken (position-aware)
            if self._position_known():
                if not self._is_amb_behind():   # ambulance now ahead of us
                    if self._passed_stamp is None:
                        self._passed_stamp = now
                        self.get_logger().info(
                            f"Ambulance overtook car "
                            f"(amb_zone={self._amb_zone} now ahead of own={self._own_zone})"
                            " — grace period starting"
                        )
                    elif (now - self._passed_stamp) >= self._clear_delay:
                        self._enter(self._RESUMING)
                else:
                    self._passed_stamp = None   # still behind — hold

            # FALLBACK: V2X emergency cleared (position not available / RSU timeout)
            elif not self._emergency_active:
                if self._clear_stamp is None:
                    self._clear_stamp = now
                elif (now - self._clear_stamp) >= self._clear_delay:
                    self._enter(self._RESUMING)
            else:
                self._clear_stamp = None

            # SAFETY: max hold timeout
            if elapsed >= self._hold_max:
                self.get_logger().warn("Hold timeout — auto-resuming")
                self._enter(self._RESUMING)

        # ── RESUMING ────────────────────────────────────────────────────────
        elif self._state == self._RESUMING:
            ramp = min(elapsed / max(self._ramp_dur, 0.1), 1.0)
            base = self._last_line_cmd
            twist.linear.x  = base.linear.x  * ramp
            twist.angular.z = base.angular.z * ramp

            if elapsed >= self._ramp_dur:
                self._enter(self._NORMAL)
                self.get_logger().info("Resumed normal lane following")

        self._cmd_pub.publish(twist)


def main(args=None):
    rclpy.init(args=args)
    node = EmergencyHandlerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()


if __name__ == '__main__':
    main()
