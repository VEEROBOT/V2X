#!/usr/bin/env python3
"""
V2X Ambulance Robot — stripped bringup launch file.

Same minimal hardware stack as the car, but WITHOUT the emergency_handler
node.  The line follower publishes directly to /cmd_vel_nav (remapped).
The v2x_bridge runs in 'ambulance' role: its /v2x/emergency_detected topic
represents "I am an emergency vehicle broadcasting right now", which will
drive the RSU integration in step 3.

Node graph
  lyra_bridge      (STM32 serial ↔ ROS2)
  wheel_odom_node  (encoder → /wheel/odom)
  camera_node      (PiCamera → /camera/image_raw)
  cmd_vel_gate     (priority mux: joystick > /cmd_vel_nav → /cmd_vel)
  line_follower    (/camera/image_raw → /cmd_vel_nav  [remapped])
  v2x_bridge       (manual service → /v2x/emergency_detected, future: OBU broadcast)

Usage
  ros2 launch v2x_robot ambulance.launch.py

  # Broadcast emergency (triggers RSU to alert car in step 3)
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
                                               description='Path to OBU JSON config (obu2_config.json)')
    car_ip_arg         = DeclareLaunchArgument('car_ip',         default_value='',
                                               description='IP/hostname of car robot for position sharing')

    use_joystick   = LaunchConfiguration('joystick')
    debug_image    = LaunchConfiguration('debug_image')
    debug_position = LaunchConfiguration('debug_position')
    obu_binary     = LaunchConfiguration('obu_binary')
    obu_config     = LaunchConfiguration('obu_config')
    car_ip         = LaunchConfiguration('car_ip')

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

    # ── 2. Wheel Odometry ─────────────────────────────────────────────────
    wheel_odom_node = Node(
        package='lyra_localization',
        executable='wheel_odom_node',
        name='wheel_odometry',
        output='screen',
        respawn=False,
    )

    # ── 3. Camera ─────────────────────────────────────────────────────────
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

    # ── 4. cmd_vel Gate ───────────────────────────────────────────────────
    cmd_vel_gate_node = Node(
        package='lyra_cmd_vel_gate',
        executable='cmd_vel_gate',
        name='cmd_vel_gate',
        output='screen',
        parameters=[{'auto_arm_for_nav': True}],
        respawn=True,
        respawn_delay=1.0,
    )

    # ── 5. Line Follower → /cmd_vel_nav (no emergency handler needed) ─────
    # lane_offset_px=0: ambulance follows WHITE CENTRE LINE (same as car).
    # Ambulance runs faster (linear_speed=0.28) so it catches up from behind.
    # /cmd_vel_line is remapped to /cmd_vel_nav so it feeds the gate directly.
    line_follower_node = Node(
        package='v2x_robot',
        executable='line_follower_node',
        name='line_follower',
        parameters=[
            line_follower_config,
            {'debug_image': debug_image,
             'lane_offset_px': 0,
             'linear_speed': 0.28},
        ],
        remappings=[('/cmd_vel_line', '/cmd_vel_nav')],
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

    # ── 5c. Position Broadcaster (sends own position to car) ─────────────
    position_broadcaster_node = Node(
        package='v2x_robot',
        executable='position_broadcaster_node',
        name='position_broadcaster',
        parameters=[
            position_config,
            {'peer_ip': car_ip,
             'role': 'ambulance'},
        ],
        output='screen',
        respawn=True,
        respawn_delay=2.0,
    )

    # ── 6. V2X Bridge (ambulance role: broadcasts emergency status) ───────
    v2x_bridge_node = Node(
        package='v2x_robot',
        executable='v2x_bridge_node',
        name='v2x_bridge',
        output='screen',
        parameters=[{
            'role':        'ambulance',
            'obu_binary':  obu_binary,
            'obu_config':  obu_config,
            'manual_mode': True,    # flip to False when OBU binary is ready (step 3)
        }],
        respawn=True,
        respawn_delay=2.0,
    )

    # ── Optional: Joystick ────────────────────────────────────────────────
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
            'enable_button': 4,
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
            LogInfo(msg='║         V2X AMBULANCE ROBOT READY                    ║'),
            LogInfo(msg='║  Lane following  : ACTIVE                            ║'),
            LogInfo(msg='║  V2X broadcast   : STANDBY (manual mode)             ║'),
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
        car_ip_arg,

        # Core stack
        lyra_bridge_node,
        wheel_odom_node,
        camera_node,
        cmd_vel_gate_node,

        # V2X lane-following + position stack (no emergency_handler — ambulance drives through)
        line_follower_node,
        position_node,
        position_broadcaster_node,
        v2x_bridge_node,

        # Optional joystick
        joy_node,
        teleop_node,

        ready_msg,
    ])
