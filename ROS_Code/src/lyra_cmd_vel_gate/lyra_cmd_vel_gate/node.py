#!/usr/bin/env python3
import threading
import rclpy
from rclpy.node import Node

from geometry_msgs.msg import Twist
from sensor_msgs.msg import Joy
from std_msgs.msg import Bool


class CmdVelGate(Node):
    """
    cmd_vel gate node - Autonomous Friendly Version

    MODES:
    1. Manual Mode (joystick):
       - Requires deadman button held
       - Can use turbo
       - Manually arm/disarm with buttons

    2. Autonomous Mode (navigation):
       - Auto-arms when nav commands arrive
       - NO deadman required
       - Joystick can override anytime (with deadman)
       - Manual disarm stops everything

    SAFETY:
    - Manual disarm → immediate STOP
    - Joystick override always available (deadman + stick movement)
    """

    def __init__(self):
        super().__init__('cmd_vel_gate')

        # ==============================
        # PARAMETERS
        # ==============================
        self.declare_parameter('deadman_button', 4)
        self.declare_parameter('turbo_button', 5)
        self.declare_parameter('normal_scale', 1.0)
        self.declare_parameter('turbo_scale', 1.8)
        self.declare_parameter('joystick_timeout', 0.5)
        self.declare_parameter('auto_arm_for_nav', True)

        self.deadman_button = self.get_parameter('deadman_button').value
        self.turbo_button = self.get_parameter('turbo_button').value
        self.normal_scale = self.get_parameter('normal_scale').value
        self.turbo_scale = self.get_parameter('turbo_scale').value
        self.joystick_timeout = self.get_parameter('joystick_timeout').value
        self.auto_arm = self.get_parameter('auto_arm_for_nav').value
        self.armed_lock = threading.Lock()

        # ==============================
        # STATE
        # ==============================
        self.deadman_pressed = False
        self.turbo_pressed = False
        self.manually_armed = False
        self._last_armed_state = False
        
        # Separate storage for joystick vs nav commands
        self.last_joy_cmd = Twist()
        self.last_nav_cmd = Twist()
        self.last_joy_time = self.get_clock().now()
        self.last_nav_time = self.get_clock().now()
        
        # FIX: State tracking for log spam prevention
        self._override_logged = False

        # ==============================
        # SUBSCRIBERS
        # ==============================
        self.create_subscription(Twist, '/cmd_vel_joy', self.joy_cmd_cb, 10)
        self.create_subscription(Twist, '/cmd_vel_nav', self.nav_cmd_cb, 10)
        self.create_subscription(Joy, '/joy', self.joy_cb, 10)
        self.create_subscription(Bool, '/lyra/armed', self.armed_cb, 10)

        # ==============================
        # PUBLISHER
        # ==============================
        self.pub_cmd = self.create_publisher(Twist, '/cmd_vel', 10)
        self.pub_armed = self.create_publisher(Bool, '/lyra/armed', 10)

        # Timer to arbitrate between joy and nav commands
        self.create_timer(0.05, self.publish_cmd)  # 20 Hz

        self.get_logger().info(f"cmd_vel gate ACTIVE (auto_arm={self.auto_arm})")

    # ==============================
    # CALLBACKS
    # ==============================
    def armed_cb(self, msg: Bool):
        with self.armed_lock:
            new_state = msg.data
            if new_state != self._last_armed_state:
                if new_state:
                    self.get_logger().info("Robot ARMED")
                else:
                    self.get_logger().info("Robot DISARMED")
                self._last_armed_state = new_state
            self.manually_armed = new_state
        #if not self.manually_armed:
        #    self.get_logger().info("Manual DISARM received")

    def joy_cb(self, msg: Joy):
        if len(msg.buttons) > self.deadman_button:
            self.deadman_pressed = msg.buttons[self.deadman_button] == 1
        if len(msg.buttons) > self.turbo_button:
            self.turbo_pressed = msg.buttons[self.turbo_button] == 1

    def joy_cmd_cb(self, msg: Twist):
        """Store joystick commands"""
        self.last_joy_cmd = msg
        self.last_joy_time = self.get_clock().now()

    def nav_cmd_cb(self, msg: Twist):
        """Store navigation commands"""
        self.last_nav_cmd = msg
        self.last_nav_time = self.get_clock().now()

    def is_armed(self) -> bool:
        """
        Determine if robot should be armed:
        - Always armed if manually armed via joystick
        - Auto-arm if navigation is sending commands (if enabled)
        """
        with self.armed_lock:
            if self.manually_armed:
                return True
        
        if self.auto_arm:
            # Auto-arm if we've received nav commands recently
            time_since_nav = (self.get_clock().now() - self.last_nav_time).nanoseconds / 1e9
            nav_active = (time_since_nav < 2.0 and self.is_nonzero(self.last_nav_cmd))
            return nav_active
        
        return False

    def publish_cmd(self):
        """
        Arbitrate between joystick and nav commands:
        1. If NOT armed (manual disarm) → STOP
        2. If deadman + recent joystick → Use joystick (OVERRIDE)
        3. If nav commands active → Use nav (AUTO-ARM if enabled)
        4. Otherwise → STOP
        """
        
        armed = self.is_armed()
        
        # NOT ARMED = STOP (unless auto-arm will handle it)
        if not armed and not self.auto_arm:
            self.pub_cmd.publish(Twist())
            self._override_logged = False  # Reset log state
            return

        # Check if joystick is actively being used
        time_since_joy = (self.get_clock().now() - self.last_joy_time).nanoseconds / 1e9
        joystick_active = (self.deadman_pressed and 
                          time_since_joy < self.joystick_timeout and
                          self.is_nonzero(self.last_joy_cmd))

        if joystick_active:
            # JOYSTICK OVERRIDE: Use joystick command with scaling
            # FIX: Only log once when override starts
            if not self.manually_armed and not self._override_logged:
                self.get_logger().info("Joystick override (auto-arming for manual control)")
                self._override_logged = True
            
            scale = self.turbo_scale if self.turbo_pressed else self.normal_scale
            gated = self.scale_twist(self.last_joy_cmd, scale)
            self.pub_cmd.publish(gated)
            
        elif armed or self.is_nonzero(self.last_nav_cmd):
            # USE NAV COMMAND (auto-armed or manually armed)
            self.pub_cmd.publish(self.last_nav_cmd)
            self._override_logged = False  # Reset when not in joystick mode
        else:
            # No active commands
            self.pub_cmd.publish(Twist())
            self._override_logged = False  # Reset log state

    def is_nonzero(self, twist: Twist) -> bool:
        """Check if twist has any non-zero values"""
        return (abs(twist.linear.x) > 0.01 or 
                abs(twist.linear.y) > 0.01 or 
                abs(twist.angular.z) > 0.01)

    def scale_twist(self, twist: Twist, scale: float) -> Twist:
        """Apply scaling to twist message"""
        scaled = Twist()
        scaled.linear.x = twist.linear.x * scale
        scaled.linear.y = twist.linear.y * scale
        scaled.linear.z = twist.linear.z * scale
        scaled.angular.x = twist.angular.x * scale
        scaled.angular.y = twist.angular.y * scale
        scaled.angular.z = twist.angular.z * scale
        return scaled


def main(args=None):
    rclpy.init(args=args)
    node = CmdVelGate()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        # rclpy.shutdown() removed - let launch system handle it


if __name__ == '__main__':
    main()
