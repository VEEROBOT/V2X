#!/usr/bin/env python3
"""
V2X Car Robot — stripped bringup launch file.

Starts only what is needed for V2X lane-following + emergency evasion.
No LiDAR, no SLAM, no Nav2, no EKF, no URDF/robot_state_publisher.

Node graph
  lyra_bridge            (STM32 serial ↔ ROS2)
  wheel_odom_node        (encoder → /wheel/odom, no EKF)
  camera_node            (PiCamera → /camera/image_raw)
  cmd_vel_gate           (priority mux: joystick > /cmd_vel_nav → /cmd_vel)
  line_follower          (/camera/image_raw → /cmd_vel_line)
  position_node          (/camera/image_raw → /robot/position  via AprilTag)
  position_broadcaster   (/robot/position ↔ UDP peer ↔ /v2x/peer_position)
  emergency_handler      (/cmd_vel_line + emergency + positions → /cmd_vel_nav)
  v2x_bridge             (OBU subprocess / manual service → /v2x/emergency_detected)

Usage
  # Normal run (position sharing disabled until ambulance_ip is set)
  ros2 launch v2x_robot car.launch.py

  # With AprilTag position sharing enabled
  ros2 launch v2x_robot car.launch.py ambulance_ip:=192.168.1.x

  # With joystick override (deadman = button 4)
  ros2 launch v2x_robot car.launch.py joystick:=true

  # Debug lane detection image
  ros2 launch v2x_robot car.launch.py debug_image:=true

  # Debug AprilTag detection
  ros2 launch v2x_robot car.launch.py debug_position:=true

  # With real OBU binary (step 3)
  ros2 launch v2x_robot car.launch.py \\
    obu_binary:=/home/pi/v2x/obu/build/obu_client \\
    obu_config:=/home/pi/v2x/obu/config/obu1_config.json \\
    ambulance_ip:=ambulance-robot.local

  # Manual emergency test (after launch, in another terminal)
  ros2 service call /v2x/set_emergency std_srvs/srv/SetBool "{data: true}"
  ros2 service call /v2x/set_emergency std_srvs/srv/SetBool "{data: false}"
"""

import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo, TimerAction
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():

    # ── Package directories ────────────────────────────────────────────────
    lyra_bridge_dir = get_package_share_directory('lyra_bridge')
    v2x_robot_dir   = get_package_share_directory('v2x_robot')

    lyra_params          = os.path.join(lyra_bridge_dir, 'config', 'lyra_params.yaml')
    line_follower_config = os.path.join(v2x_robot_dir,   'config', 'line_follower.yaml')
    position_config      = os.path.join(v2x_robot_dir,   'config', 'position.yaml')

    # ── Launch arguments ──────────────────────────────────────────────────
    joystick_arg       = DeclareLaunchArgument('joystick',       default_value='false',
                                               description='Enable joystick (button 4 = deadman)')
    debug_image_arg    = DeclareLaunchArgument('debug_image',    default_value='false',
                                               description='Publish /line_follower/debug image')
    debug_position_arg = DeclareLaunchArgument('debug_position', default_value='false',
                                               description='Publish /position/debug AprilTag image')
    obu_binary_arg     = DeclareLaunchArgument('obu_binary',     default_value='',
                                               description='Path to compiled OBU binary')
    obu_config_arg     = DeclareLaunchArgument('obu_config',     default_value='',
                                               description='Path to OBU JSON config file')
    ambulance_ip_arg   = DeclareLaunchArgument('ambulance_ip',   default_value='',
                                               description='IP/hostname of ambulance robot for position sharing')

    use_joystick   = LaunchConfiguration('joystick')
    debug_image    = LaunchConfiguration('debug_image')
    debug_position = LaunchConfiguration('debug_position')
    obu_binary     = LaunchConfiguration('obu_binary')
    obu_config     = LaunchConfiguration('obu_config')
    ambulance_ip   = LaunchConfiguration('ambulance_ip')

    # ── 1. STM32 Bridge ───────────────────────────────────────────────────
    lyra_bridge_node = Node(
        package='lyra_bridge',
        executable='lyra_node',
        name='lyra_bridge',
        parameters=[lyra_params],
        output='screen',
        respawn=True,
        respawn_delay=2.0,
    )

    # ── 2. Wheel Odometry (encoder ticks → /wheel/odom, no EKF) ──────────
    wheel_odom_node = Node(
        package='lyra_localization',
        executable='wheel_odom_node',
        name='wheel_odometry',
        output='screen',
        respawn=False,
    )

    # ── 3. Camera (PiCamera via libcamera) ────────────────────────────────
    camera_node = Node(
        package='camera_ros',
        executable='camera_node',
        name='pi_camera',
        output='screen',
        parameters=[{
            'camera':    0,
            'width':   320,
            'height':  240,
            'format':  'BGR888',
            'frame_id': 'camera_optical_link',
        }],
        respawn=False,
    )

    # ── 4. cmd_vel Gate (joystick > /cmd_vel_nav) ────────────────────────
    # auto_arm_for_nav=True means the gate arms itself as soon as
    # emergency_handler starts publishing on /cmd_vel_nav.
    cmd_vel_gate_node = Node(
        package='lyra_cmd_vel_gate',
        executable='cmd_vel_gate',
        name='cmd_vel_gate',
        output='screen',
        parameters=[{'auto_arm_for_nav': True}],
        respawn=True,
        respawn_delay=1.0,
    )

    # ── 5. Line Follower (/camera/image_raw → /cmd_vel_line) ─────────────
    # lane_offset_px=0: car follows the WHITE CENTRE LINE (default travel path).
    # Both robots travel on the centre line in normal operation.
    # The ambulance (faster) catches up from behind; car then yields LEFT.
    line_follower_node = Node(
        package='v2x_robot',
        executable='line_follower_node',
        name='line_follower',
        parameters=[
            line_follower_config,
            {'debug_image': debug_image,
             'lane_offset_px': 0},
        ],
        output='screen',
        respawn=True,
        respawn_delay=1.0,
    )

    # ── 5b. Position Node (AprilTag → /robot/position) ────────────────────
    position_node = Node(
        package='v2x_robot',
        executable='position_node',
        name='position',
        parameters=[
            position_config,
            {'debug_image': debug_position},
        ],
        output='screen',
        respawn=True,
        respawn_delay=2.0,
    )

    # ── 5c. Position Broadcaster (UDP peer-to-peer position sharing) ──────
    position_broadcaster_node = Node(
        package='v2x_robot',
        executable='position_broadcaster_node',
        name='position_broadcaster',
        parameters=[
            position_config,
            {'peer_ip': ambulance_ip,
             'role': 'car'},
        ],
        output='screen',
        respawn=True,
        respawn_delay=2.0,
    )

    # ── 6. Emergency Handler (/cmd_vel_line + V2X + positions → /cmd_vel_nav)
    emergency_handler_node = Node(
        package='v2x_robot',
        executable='emergency_handler_node',
        name='emergency_handler',
        output='screen',
        respawn=True,
        respawn_delay=1.0,
    )

    # ── 7. V2X Bridge (OBU / manual → /v2x/emergency_detected) ──────────
    v2x_bridge_node = Node(
        package='v2x_robot',
        executable='v2x_bridge_node',
        name='v2x_bridge',
        output='screen',
        parameters=[{
            'role':         'car',
            'obu_binary':   obu_binary,
            'obu_config':   obu_config,
            'manual_mode':  True,   # flip to False when OBU binary is wired up (step 3)
        }],
        respawn=True,
        respawn_delay=2.0,
    )

    # ── Optional: Joystick (manual override during testing) ───────────────
    joy_node = Node(
        package='joy',
        executable='joy_node',
        name='joy_node',
        output='screen',
        condition=IfCondition(use_joystick),
        respawn=True,
        respawn_delay=2.0,
    )

    teleop_node = Node(
        package='teleop_twist_joy',
        executable='teleop_node',
        name='teleop_twist_joy',
        output='screen',
        parameters=[{
            'require_enable_button': True,
            'enable_button': 4,         # LB / L1
            'scale_linear':  {'x': 0.4},
            'scale_angular': {'yaw': 1.0},
        }],
        remappings=[('/cmd_vel', '/cmd_vel_joy')],
        condition=IfCondition(use_joystick),
        respawn=True,
        respawn_delay=2.0,
    )

    # ── Ready message ─────────────────────────────────────────────────────
    ready_msg = TimerAction(
        period=4.0,
        actions=[
            LogInfo(msg=''),
            LogInfo(msg='╔══════════════════════════════════════════════════════╗'),
            LogInfo(msg='║         V2X CAR ROBOT READY                          ║'),
            LogInfo(msg='║  Lane following  : ACTIVE                            ║'),
            LogInfo(msg='║  V2X emergency   : MONITORING (manual mode)          ║'),
            LogInfo(msg='║                                                      ║'),
            LogInfo(msg='║  Trigger:  ros2 service call /v2x/set_emergency      ║'),
            LogInfo(msg='║            std_srvs/srv/SetBool "{data: true}"       ║'),
            LogInfo(msg='║  Clear:    ... "{data: false}"                       ║'),
            LogInfo(msg='╚══════════════════════════════════════════════════════╝'),
            LogInfo(msg=''),
        ],
    )

    return LaunchDescription([
        # Arguments
        joystick_arg,
        debug_image_arg,
        debug_position_arg,
        obu_binary_arg,
        obu_config_arg,
        ambulance_ip_arg,

        # Core stack
        lyra_bridge_node,
        wheel_odom_node,
        camera_node,
        cmd_vel_gate_node,

        # V2X lane-following + position stack
        line_follower_node,
        position_node,
        position_broadcaster_node,
        emergency_handler_node,
        v2x_bridge_node,

        # Optional joystick
        joy_node,
        teleop_node,

        ready_msg,
    ])
