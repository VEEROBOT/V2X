"""
Lyra Bridge - Main ROS2 Node (THREAD-SAFE VERSION)
FINAL CORRECTED VERSION v1.5

CRITICAL FIXES:
1. Motor commands timeout after 500ms (THREAD-SAFE)
2. Stale commands are cleared safely
3. STOP sent when disarmed
4. STOP sent when cmd_vel times out
5. Sequence number is thread-safe (Issue #4)
6. Motor control logic has no race conditions (Issue #2)
"""

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from geometry_msgs.msg import Twist
from sensor_msgs.msg import Imu
from std_msgs.msg import Float32, Float32MultiArray, Int32MultiArray, Bool
from std_srvs.srv import Trigger, SetBool
import threading
import time
import math
from typing import Optional

from .transport import SerialTransport
from .protocol import (
    parse_from_buffer,
    build_arm_command,
    build_disarm_command,
    build_emergency_stop_command,
    build_set_wheel_vel_command,
    build_get_telemetry_command,
    build_heartbeat_command,
    build_set_ros_mode_command,
)

from .telemetry import parse_telemetry, parse_status_flags


CMD_GET_TELEMETRY = 0x85
RX_POLL_RATE_HZ = 50
RX_POLL_INTERVAL_S = 1.0 / RX_POLL_RATE_HZ
ROS_MODE_INIT_DELAY_S = 0.5


class LyraBridge(Node):
    """ROS2 bridge node for Lyra motor controller (THREAD-SAFE)"""

    def __init__(self):
        super().__init__('lyra_bridge')

        # Parameters
        self.declare_parameters(
            namespace='',
            parameters=[
                ('serial.port', '/dev/ttyAMA0'),
                ('serial.baudrate', 115200),
                ('robot.wheel_radius_m', 0.065),
                ('robot.track_width_m', 0.377),
                ('robot.max_wheel_speed_rad_s', 15.7),
                ('control.cmd_vel_timeout_s', 0.5),
                ('control.telemetry_rate_hz', 10.0),
                ('control.heartbeat_rate_hz', 1.0),
                ('topics.cmd_vel', '/cmd_vel'),
                ('topics.wheel_rpm', '/wheel_rpm'),
                ('topics.wheel_ticks', '/wheel_ticks'),
                ('topics.battery_voltage', '/battery_voltage'),
                ('topics.imu_raw', '/imu/data_raw'),
                ('topics.armed_status', '/lyra/armed'),
                ('control.battery_low_threshold_v', 10.0),
            ]
        )

        self.serial_port = self.get_parameter('serial.port').value
        self.serial_baud = self.get_parameter('serial.baudrate').value
        self.wheel_radius = self.get_parameter('robot.wheel_radius_m').value
        self.track_width = self.get_parameter('robot.track_width_m').value
        self.max_wheel_speed = self.get_parameter('robot.max_wheel_speed_rad_s').value
        self.cmd_timeout = self.get_parameter('control.cmd_vel_timeout_s').value
        self.telem_rate = self.get_parameter('control.telemetry_rate_hz').value
        self.heartbeat_rate = self.get_parameter('control.heartbeat_rate_hz').value
        self.battery_threshold = self.get_parameter('control.battery_low_threshold_v').value

        # THREAD-SAFE State variables
        self.seq = 0
        self.seq_lock = threading.Lock()
        
        self.armed = False
        self.armed_lock = threading.Lock()
        
        self.last_cmd_time = time.monotonic()
        self.cmd_lock = threading.Lock()
        self.latest_cmd_vel: Optional[Twist] = None
        
        self.last_rx_time = time.monotonic()
        self.rx_lock = threading.Lock()

        # Motor control loop (20 Hz)
        self.motor_timer = self.create_timer(0.05, self._motor_control_loop)

        # Transport layer
        self.transport = SerialTransport(self.serial_port, self.serial_baud, timeout=0.0)
        self.running = True
        self.rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
        self.rx_thread.start()

        # Publishers
        qos_sensor = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10
        )

        self.pub_rpm = self.create_publisher(
            Float32MultiArray,
            self.get_parameter('topics.wheel_rpm').value,
            qos_sensor
        )

        self.pub_ticks = self.create_publisher(
            Int32MultiArray,
            self.get_parameter('topics.wheel_ticks').value,
            qos_sensor
        )

        self.pub_battery = self.create_publisher(
            Float32,
            self.get_parameter('topics.battery_voltage').value,
            qos_sensor
        )

        self.pub_imu = self.create_publisher(
            Imu,
            self.get_parameter('topics.imu_raw').value,
            qos_sensor
        )

        self.pub_armed = self.create_publisher(
            Bool,
            self.get_parameter('topics.armed_status').value,
            10
        )

        # Subscribers
        self.create_subscription(
            Twist,
            self.get_parameter('topics.cmd_vel').value,
            self._cmd_vel_callback,
            10
        )

        # Services
        self.create_service(Trigger, '/lyra/arm', self._arm_service)
        self.create_service(Trigger, '/lyra/disarm', self._disarm_service)
        self.create_service(Trigger, '/lyra/emergency_stop', self._estop_service)

        # Telemetry request timer
        telem_period = 1.0 / self.telem_rate
        self.telem_timer = self.create_timer(telem_period, self._request_telemetry)

        # Heartbeat timer
        heartbeat_period = 1.0 / self.heartbeat_rate
        self.heartbeat_timer = self.create_timer(heartbeat_period, self._send_heartbeat)

        # ROS mode initialization (delayed)
        self._ros_mode_initialized = False
        self._init_timer = self.create_timer(ROS_MODE_INIT_DELAY_S, self._init_ros_mode)

        self.get_logger().info(f"Lyra Bridge started on {self.serial_port}")
        self.get_logger().info("Robot starts DISARMED - use /lyra/arm service or joystick to arm")

    def _next_seq(self) -> int:
        """Get next sequence number (THREAD-SAFE)"""
        with self.seq_lock:
            self.seq = (self.seq + 1) % 256
            return self.seq

    def _init_ros_mode(self):
        """Initialize ROS mode (ONE TIME ONLY)"""
        if not self._ros_mode_initialized:
            success = self._send_command(build_set_ros_mode_command(self._next_seq(), True))
            if success:
                self._ros_mode_initialized = True
                self.get_logger().info("ROS mode enabled on STM32")
                self._init_timer.cancel()

    def _rx_loop(self):
        """Background thread for receiving data from STM32"""
        while self.running and rclpy.ok():
            try:
                bytes_read = self.transport.poll()
                
                if bytes_read > 0:
                    with self.rx_lock:
                        self.last_rx_time = time.monotonic()
                    
                    # Parse packets from buffer
                    while True:
                        result = parse_from_buffer(self.transport.get_buffer())
                        if result is None:
                            break
                        
                        seq, cmd, payload = result
                        self._handle_packet(cmd, payload)
                
                time.sleep(RX_POLL_INTERVAL_S)
                
            except Exception as e:
                self.get_logger().error(f"RX loop error: {e}", throttle_duration_sec=5.0)
                time.sleep(0.1)

    def _handle_packet(self, cmd: int, payload: bytes):
        """Handle received packets from STM32"""
        if cmd == CMD_GET_TELEMETRY:
            telem = parse_telemetry(payload)
            if telem is None:
                self.get_logger().warn("Failed to parse telemetry", throttle_duration_sec=5.0)
                return
            
            # Parse status flags
            status = parse_status_flags(telem['status_flags'])
            
            # Update armed state
            with self.armed_lock:
                prev_armed = self.armed
                self.armed = status.get('armed', False)
                if self.armed != prev_armed:
                    state = "ARMED" if self.armed else "DISARMED"
                    self.get_logger().info(f"Robot {state}")
            
            # Publish armed status
            armed_msg = Bool()
            armed_msg.data = self.armed
            self.pub_armed.publish(armed_msg)
            
            # Publish wheel RPM
            rpm_msg = Float32MultiArray()
            rpm_msg.data = telem['wheel_rpm']
            self.pub_rpm.publish(rpm_msg)
            
            # Publish wheel ticks
            ticks_msg = Int32MultiArray()
            ticks_msg.data = telem['wheel_ticks']
            self.pub_ticks.publish(ticks_msg)
            
            # Publish battery voltage
            battery_msg = Float32()
            battery_msg.data = telem['battery_v']
            self.pub_battery.publish(battery_msg)
            
            # Publish IMU data
            imu_msg = Imu()
            imu_msg.header.stamp = self.get_clock().now().to_msg()
            imu_msg.header.frame_id = 'imu_link'
            imu_msg.linear_acceleration.x = telem['accel_x']
            imu_msg.linear_acceleration.y = telem['accel_y']
            imu_msg.linear_acceleration.z = telem['accel_z']
            imu_msg.angular_velocity.x = telem['gyro_x']
            imu_msg.angular_velocity.y = telem['gyro_y']
            imu_msg.angular_velocity.z = telem['gyro_z']
            self.pub_imu.publish(imu_msg)

    def _cmd_vel_callback(self, msg: Twist):
        """Handle incoming velocity commands (THREAD-SAFE)"""
        with self.cmd_lock:
            self.latest_cmd_vel = msg
            self.last_cmd_time = time.monotonic()

    def _motor_control_loop(self):
        """Motor control loop - runs at 20Hz (THREAD-SAFE)"""
        # Check armed state
        with self.armed_lock:
            is_armed = self.armed
        
        if not is_armed:
            zero_cmd = build_set_wheel_vel_command(self._next_seq(), [0.0, 0.0, 0.0, 0.0])
            self._send_command(zero_cmd)
            return
        
        # ATOMIC CAPTURE of command state
        with self.cmd_lock:
            cmd_vel = self.latest_cmd_vel
            cmd_time = self.last_cmd_time

        # Process outside lock to avoid holding lock during computation
        if cmd_vel is None:
            # No command received yet - send STOP
            zero_cmd = build_set_wheel_vel_command(self._next_seq(), [0.0, 0.0, 0.0, 0.0])
            self._send_command(zero_cmd)
            return

        # Calculate command age
        cmd_age_s = time.monotonic() - cmd_time

        if cmd_age_s > self.cmd_timeout:
            # Command timed out - send STOP
            zero_cmd = build_set_wheel_vel_command(self._next_seq(), [0.0, 0.0, 0.0, 0.0])
            self._send_command(zero_cmd)
            self.get_logger().warn(
                f"cmd_vel timeout ({cmd_age_s:.2f}s) - stopping",
                throttle_duration_sec=1.0
            )
            return

        # Convert cmd_vel to wheel velocities
        wheel_vels = self._inverse_kinematics(cmd_vel.linear.x, cmd_vel.angular.z)
        
        # Send to STM32
        frame = build_set_wheel_vel_command(self._next_seq(), wheel_vels)
        self._send_command(frame)

    def _inverse_kinematics(self, vx: float, wz: float) -> list:
        """Convert cmd_vel to wheel velocities (rad/s)"""
        half_track = self.track_width / 2.0
        v_left = vx - (wz * half_track)
        v_right = vx + (wz * half_track)

        w_left = v_left / self.wheel_radius
        w_right = v_right / self.wheel_radius

        w_left = max(min(w_left, self.max_wheel_speed), -self.max_wheel_speed)
        w_right = max(min(w_right, self.max_wheel_speed), -self.max_wheel_speed)

        return [w_left, w_left, w_right, w_right]  # [FL, BL, BR, FR]

    def _send_command(self, frame: bytes) -> bool:
        """Send command frame to STM32"""
        return self.transport.write(frame)

    def _request_telemetry(self):
        """Request telemetry from STM32"""
        frame = build_get_telemetry_command(self._next_seq())
        self._send_command(frame)

    def _send_heartbeat(self):
        """Send heartbeat to STM32"""
        frame = build_heartbeat_command(self._next_seq())
        self._send_command(frame)

    def _arm_service(self, request, response):
        try:
            frame = build_arm_command(self._next_seq())
            success = self._send_command(frame)
            response.success = success
            response.message = "ARM command sent" if success else "Failed to send ARM"
            self.get_logger().info(f"ARM service: {response.message}")
        except Exception as e:
            response.success = False
            response.message = f"ARM service exception: {str(e)}"
            self.get_logger().error(response.message)
        return response

    def _disarm_service(self, request, response):
        """DISARM service handler"""
        try:
            frame = build_disarm_command(self._next_seq())
            success = self._send_command(frame)
            response.success = success
            response.message = "DISARM command sent" if success else "Failed to send DISARM"
            self.get_logger().info(f"DISARM service: {response.message}")
        except Exception as e:
            response.success = False
            response.message = f"DISARM service exception: {str(e)}"
            self.get_logger().error(response.message)
        return response

    def _estop_service(self, request, response):
        """Emergency stop service handler"""
        try:
            frame = build_emergency_stop_command(self._next_seq())
            success = self._send_command(frame)
            response.success = success
            response.message = "EMERGENCY STOP sent" if success else "Failed to send ESTOP"
            self.get_logger().warn(f"ESTOP service: {response.message}")
        except Exception as e:
            response.success = False
            response.message = f"ESTOP service exception: {str(e)}"
            self.get_logger().error(response.message)
        return response

    def destroy_node(self):
        """Clean shutdown."""
        self.get_logger().info("Shutting down Lyra Bridge...")
        self.running = False
        if self.rx_thread.is_alive():
            self.rx_thread.join(timeout=1.0)
        self.transport.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = LyraBridge()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        # rclpy.shutdown() removed - let launch system handle it


if __name__ == '__main__':
    main()
