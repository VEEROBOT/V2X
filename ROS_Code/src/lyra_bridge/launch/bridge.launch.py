"""Launch file for Lyra Bridge node."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    """Generate launch description for Lyra Bridge."""
    
    # Declare launch arguments
    serial_port_arg = DeclareLaunchArgument(
        'serial_port',
        default_value='/dev/ttyAMA0',
        description='Serial port for STM32 communication'
    )
    
    serial_baudrate_arg = DeclareLaunchArgument(
        'serial_baudrate',
        default_value='115200',
        description='Serial baudrate'
    )
    
    auto_arm_arg = DeclareLaunchArgument(
        'auto_arm',
        default_value='true',
        description='Auto-ARM robot on cmd_vel'
    )
    
    cmd_vel_timeout_arg = DeclareLaunchArgument(
        'cmd_vel_timeout',
        default_value='0.5',
        description='Cmd_vel timeout in seconds'
    )
    
    # Lyra Bridge node
    lyra_bridge_node = Node(
        package='lyra_bridge',
        executable='lyra_node',
        name='lyra_bridge',
        output='screen',
        parameters=[{
            'serial.port': LaunchConfiguration('serial_port'),
            'serial.baudrate': LaunchConfiguration('serial_baudrate'),
            'control.auto_arm': LaunchConfiguration('auto_arm'),
            'control.cmd_vel_timeout_s': LaunchConfiguration('cmd_vel_timeout'),
        }],
        remappings=[
            # Add any topic remappings here if needed
        ]
    )
    
    return LaunchDescription([
        serial_port_arg,
        serial_baudrate_arg,
        auto_arm_arg,
        cmd_vel_timeout_arg,
        lyra_bridge_node,
    ])
