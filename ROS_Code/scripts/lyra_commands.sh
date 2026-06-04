#!/bin/bash
#
# Lyra Robot Command Utility
# Quick access to common launch, control, and debugging commands
#
# Usage: source ./lyra_commands.sh
# Then use: lyra-<command>
#
# Examples:
#   lyra-launch-base           # Launch base robot
#   lyra-launch-slam           # Launch with SLAM
#   lyra-arm                   # ARM the robot
#   lyra-disarm                # DISARM the robot
#   lyra-stop                  # Emergency stop
#   lyra-status                # Show robot status
#

# NOTE: Do NOT use 'set -o errexit' here - this file is sourced, not executed
# Using errexit would crash the user's terminal on any failed command

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Workspace directory
LYRA_WS="${HOME}/lyra_ws"  # Change if different

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

lyra_print_header() {
    echo -e "${BLUE}[LYRA] $1${NC}"
}

lyra_print_success() {
    echo -e "${GREEN}[✓] $1${NC}"
}

lyra_print_error() {
    echo -e "${RED}[✗] $1${NC}"
}

lyra_print_warning() {
    echo -e "${YELLOW}[!] $1${NC}"
}

# Check if ROS is initialized
lyra_check_ros() {
    if ! command -v ros2 &> /dev/null; then
        lyra_print_error "ROS 2 not found. Source your ROS setup first:"
        echo "  source /opt/ros/\$ROS_DISTRO/setup.bash"
        return 1
    fi
    return 0
}

# ============================================================================
# LAUNCH COMMANDS
# ============================================================================

lyra-launch-base() {
    lyra_print_header "Launching BASE ROBOT..."
    lyra_check_ros || return 1
    
    cd "$LYRA_WS" || return 1
    ros2 launch lyra_bringup base.launch.py use_imu:=true use_camera:=true
}

lyra-launch-base-no-imu() {
    lyra_print_header "Launching BASE ROBOT (NO IMU)..."
    lyra_check_ros || return 1
    
    cd "$LYRA_WS" || return 1
    ros2 launch lyra_bringup base.launch.py use_imu:=false use_camera:=true
}

lyra-launch-base-no-camera() {
    lyra_print_header "Launching BASE ROBOT (NO CAMERA)..."
    lyra_check_ros || return 1
    
    cd "$LYRA_WS" || return 1
    ros2 launch lyra_bringup base.launch.py use_imu:=true use_camera:=false
}

lyra-launch-robot-slam() {
    lyra_print_header "Launching FULL ROBOT (SLAM MODE)..."
    lyra_check_ros || return 1
    
    cd "$LYRA_WS" || return 1
    ros2 launch lyra_bringup robot.launch.py mode:=slam
}

lyra-launch-robot-nav() {
    if [ -z "$1" ]; then
        lyra_print_error "Usage: lyra-launch-robot-nav <path/to/map.yaml>"
        return 1
    fi
    
    lyra_print_header "Launching FULL ROBOT (NAVIGATION MODE)..."
    lyra_check_ros || return 1
    
    if [ ! -f "$1" ]; then
        lyra_print_error "Map file not found: $1"
        return 1
    fi
    
    cd "$LYRA_WS" || return 1
    ros2 launch lyra_bringup robot.launch.py mode:=nav map:="$1"
}

lyra-launch-robot-teleop() {
    lyra_print_header "Launching FULL ROBOT (TELEOP MODE)..."
    lyra_check_ros || return 1
    
    cd "$LYRA_WS" || return 1
    ros2 launch lyra_bringup robot.launch.py mode:=teleop
}

lyra-launch-bridge() {
    lyra_print_header "Launching BRIDGE ONLY..."
    lyra_check_ros || return 1
    
    cd "$LYRA_WS" || return 1
    ros2 launch lyra_bridge bridge.launch.py
}

lyra-launch-rviz() {
    lyra_print_header "Launching RViz..."
    lyra_check_ros || return 1
    
    cd "$LYRA_WS" || return 1
    ros2 launch beetlebot_description display_launch.py
}

# ============================================================================
# CONTROL COMMANDS (ARM / DISARM / STOP)
# ============================================================================

lyra-arm() {
    lyra_print_header "ARM command..."
    lyra_check_ros || return 1
    
    ros2 service call /lyra/arm std_srvs/srv/Trigger
    lyra_print_success "ARM sent. Check bridge output for confirmation."
}

lyra-disarm() {
    lyra_print_header "DISARM command..."
    lyra_check_ros || return 1
    
    ros2 service call /lyra/disarm std_srvs/srv/Trigger
    lyra_print_success "DISARM sent."
}

lyra-stop() {
    lyra_print_error "EMERGENCY STOP!"
    lyra_check_ros || return 1
    
    ros2 service call /lyra/emergency_stop std_srvs/srv/Trigger
    lyra_print_success "Emergency stop sent."
}

lyra-ros-mode-on() {
    lyra_print_header "Enabling ROS mode..."
    lyra_check_ros || return 1
    
    ros2 service call /lyra/set_ros_mode std_srvs/srv/SetBool "{data: true}"
    lyra_print_success "ROS mode enabled."
}

lyra-ros-mode-off() {
    lyra_print_header "Disabling ROS mode..."
    lyra_check_ros || return 1
    
    ros2 service call /lyra/set_ros_mode std_srvs/srv/SetBool "{data: false}"
    lyra_print_success "ROS mode disabled."
}

# ============================================================================
# STATUS / MONITORING COMMANDS
# ============================================================================

lyra-status() {
    lyra_print_header "Robot Status"
    lyra_check_ros || return 1
    
    echo ""
    echo "=== NODES ==="
    ros2 node list 2>/dev/null | grep -E "lyra|bridge|odom|ekf|joy|camera" || echo "No Lyra nodes found"
    
    echo ""
    echo "=== ARMED STATUS ==="
    ros2 topic echo /lyra/armed --once 2>/dev/null || echo "Topic not available"
    
    echo ""
    echo "=== BATTERY VOLTAGE ==="
    ros2 topic echo /battery_voltage --once 2>/dev/null || echo "Topic not available"
    
    echo ""
    echo "=== WHEEL RPM ==="
    ros2 topic echo /wheel_rpm --once 2>/dev/null || echo "Topic not available"
}

lyra-battery() {
    lyra_print_header "Battery Voltage..."
    lyra_check_ros || return 1
    
    ros2 topic echo /battery_voltage "$@"
}

lyra-armed-status() {
    lyra_print_header "Armed Status..."
    lyra_check_ros || return 1
    
    ros2 topic echo /lyra/armed "$@"
}

lyra-wheel-rpm() {
    lyra_print_header "Wheel RPM..."
    lyra_check_ros || return 1
    
    ros2 topic echo /wheel_rpm "$@"
}

lyra-wheel-ticks() {
    lyra_print_header "Wheel Ticks..."
    lyra_check_ros || return 1
    
    ros2 topic echo /wheel_ticks "$@"
}

lyra-imu() {
    lyra_print_header "IMU Data..."
    lyra_check_ros || return 1
    
    ros2 topic echo /imu/data_raw "$@"
}

lyra-odom() {
    lyra_print_header "Odometry Data..."
    lyra_check_ros || return 1
    
    ros2 topic echo /odom "$@"
}

lyra-scan() {
    lyra_print_header "LiDAR Scan..."
    lyra_check_ros || return 1
    
    ros2 topic echo /scan "$@"
}

lyra-tf-tree() {
    lyra_print_header "TF Tree..."
    lyra_check_ros || return 1
    
    ros2 run tf2_tools view_frames.py 2>/dev/null || echo "Could not display TF tree"
    echo "Check frames.pdf for visualization"
}

lyra-diagnostics() {
    lyra_print_header "System Diagnostics..."
    lyra_check_ros || return 1
    
    ros2 topic echo /diagnostics "$@"
}

# ============================================================================
# NODE MANAGEMENT
# ============================================================================

lyra-nodes() {
    lyra_print_header "Active ROS Nodes"
    lyra_check_ros || return 1
    
    ros2 node list
}

lyra-topics() {
    lyra_print_header "Active ROS Topics"
    lyra_check_ros || return 1
    
    ros2 topic list
}

lyra-services() {
    lyra_print_header "Available Services"
    lyra_check_ros || return 1
    
    ros2 service list | grep -i lyra || echo "No Lyra services found"
}

lyra-node-info() {
    if [ -z "$1" ]; then
        lyra_print_error "Usage: lyra-node-info <node_name>"
        echo "Example: lyra-node-info lyra_bridge"
        return 1
    fi
    
    lyra_print_header "Node Info: $1"
    lyra_check_ros || return 1
    
    ros2 node info "/$1"
}

# ============================================================================
# PARAMETER COMMANDS
# ============================================================================

lyra-params() {
    if [ -z "$1" ]; then
        lyra_print_error "Usage: lyra-params <node_name>"
        echo "Example: lyra-params lyra_bridge"
        return 1
    fi
    
    lyra_print_header "Parameters for $1"
    lyra_check_ros || return 1
    
    ros2 param list "/$1"
}

lyra-param-get() {
    if [ -z "$1" ] || [ -z "$2" ]; then
        lyra_print_error "Usage: lyra-param-get <node_name> <param_name>"
        echo "Example: lyra-param-get lyra_bridge serial.port"
        return 1
    fi
    
    lyra_check_ros || return 1
    ros2 param get "/$1" "$2"
}

lyra-param-set() {
    if [ -z "$1" ] || [ -z "$2" ] || [ -z "$3" ]; then
        lyra_print_error "Usage: lyra-param-set <node_name> <param_name> <value>"
        echo "Example: lyra-param-set lyra_bridge control.cmd_vel_timeout_s 1.0"
        return 1
    fi
    
    lyra_check_ros || return 1
    ros2 param set "/$1" "$2" "$3"
    lyra_print_success "Parameter updated."
}

# ============================================================================
# LOGGING / DEBUGGING
# ============================================================================

lyra-log-bridge() {
    lyra_print_header "Bridge Node Logs (last 50 lines)..."
    lyra_check_ros || return 1
    
    # Try to find and display recent logs
    local log_dir="$HOME/.ros/log"
    if [ -d "$log_dir" ]; then
        find "$log_dir" -name "*bridge*" -type f -exec tail -50 {} \;
    else
        lyra_print_warning "Log directory not found. Try running a node first."
    fi
}

lyra-log-live() {
    if [ -z "$1" ]; then
        lyra_print_error "Usage: lyra-log-live <node_name>"
        echo "Example: lyra-log-live lyra_bridge"
        return 1
    fi
    
    lyra_print_header "Live Logs: $1"
    lyra_check_ros || return 1
    
    ros2 run rqt_console rqt_console
}

lyra-debug-bridge() {
    lyra_print_header "Debug: Bridge Node Details"
    lyra_check_ros || return 1
    
    echo "=== Bridge Info ==="
    ros2 node info /lyra_bridge
    
    echo ""
    echo "=== Bridge Parameters ==="
    ros2 param list /lyra_bridge
    
    echo ""
    echo "=== Bridge Subscriptions/Publications ==="
    ros2 node info /lyra_bridge | grep -A 20 "Subscriptions\|Publications"
}

# ============================================================================
# CLEANUP / KILL COMMANDS
# ============================================================================

lyra-kill() {
    lyra_print_error "Killing all Lyra nodes..."
    
    # Kill specific Lyra nodes
    pkill -f "lyra_bridge" || true
    pkill -f "cmd_vel_gate" || true
    pkill -f "wheel_odom" || true
    pkill -f "joy_teleop_wrapper" || true
    pkill -f "ekf_node" || true
    pkill -f "imu_filter" || true
    pkill -f "camera_node" || true
    pkill -f "joy_node" || true
    pkill -f "teleop_twist_joy" || true
    
    sleep 1
    lyra_print_success "All Lyra nodes killed."
}

lyra-kill-all() {
    lyra_print_error "KILLING ALL ROS 2 NODES!"
    lyra_print_warning "This will stop everything. Are you sure? (Ctrl+C to cancel)"
    read -p "Type 'yes' to confirm: " confirm
    
    if [ "$confirm" = "yes" ]; then
        pkill -f "ros2 launch" || true
        pkill -f "ros2 run" || true
        sleep 2
        lyra_print_success "All ROS 2 nodes killed."
    else
        lyra_print_warning "Cancelled."
    fi
}

lyra-cleanup() {
    lyra_print_header "Cleaning up ROS 2 resources..."
    
    # Kill all nodes
    lyra_print_warning "Killing nodes..."
    pkill -f "ros2 launch" || true
    pkill -f "ros2 run" || true
    
    sleep 1
    
    # Clear ROS temporary files
    lyra_print_warning "Clearing ROS temp files..."
    rm -rf "$HOME/.ros/log" 2>/dev/null || true
    rm -f "$HOME/.ros/roslaunch" 2>/dev/null || true
    
    # Kill ROS daemon
    ros2 daemon stop 2>/dev/null || true
    
    sleep 1
    
    lyra_print_success "Cleanup complete. ROS daemon restarting..."
    ros2 daemon start 2>/dev/null || true
}

lyra-reset() {
    lyra_print_error "FULL SYSTEM RESET!"
    lyra_print_warning "This will kill all nodes and clear all logs. Are you sure? (Ctrl+C to cancel)"
    read -p "Type 'yes' to confirm: " confirm
    
    if [ "$confirm" = "yes" ]; then
        lyra_cleanup
        lyra_print_success "System reset complete. You can now restart nodes."
    else
        lyra_print_warning "Cancelled."
    fi
}

# ============================================================================
# TESTING / VERIFICATION
# ============================================================================

lyra-test-hardware() {
    lyra_print_header "Testing Hardware Connectivity..."
    lyra_check_ros || return 1
    
    echo ""
    echo "=== Testing Bridge Node ==="
    if ros2 service call /lyra/arm std_srvs/srv/Trigger --no-display-reply 2>/dev/null; then
        lyra_print_success "Bridge node is responsive"
    else
        lyra_print_error "Bridge node not responding"
    fi
    
    echo ""
    echo "=== Testing Serial Connection ==="
    if [ -c /dev/ttyAMA0 ]; then
        lyra_print_success "Serial port /dev/ttyAMA0 exists"
    else
        lyra_print_error "Serial port /dev/ttyAMA0 not found"
    fi
    
    echo ""
    echo "=== Testing Joystick ==="
    if ls /dev/input/js* 2>/dev/null; then
        lyra_print_success "Joystick device found"
    else
        lyra_print_warning "No joystick device found"
    fi
    
    echo ""
    echo "=== Testing Camera ==="
    if ls /dev/video* 2>/dev/null; then
        lyra_print_success "Camera device found"
    else
        lyra_print_warning "No camera device found"
    fi
}

lyra-test-connectivity() {
    lyra_print_header "Testing ROS Connectivity..."
    lyra_check_ros || return 1
    
    # Test if we can see topics
    echo "Testing topic discovery (5 second timeout)..."
    if timeout 5 ros2 topic list &>/dev/null; then
        lyra_print_success "ROS network operational"
    else
        lyra_print_error "Cannot reach ROS network"
    fi
}

# ============================================================================
# HELP
# ============================================================================

lyra-help() {
    cat << 'EOF'
╔════════════════════════════════════════════════════════════════════════════╗
║                      LYRA ROBOT COMMAND UTILITY                            ║
╚════════════════════════════════════════════════════════════════════════════╝

LAUNCH COMMANDS:
  lyra-launch-base              Launch base robot only
  lyra-launch-base-no-imu       Launch base without IMU
  lyra-launch-base-no-camera    Launch base without camera
  lyra-launch-robot-slam        Launch full robot in SLAM mode
  lyra-launch-robot-nav <map>   Launch full robot in NAV mode (requires map)
  lyra-launch-robot-teleop      Launch full robot in TELEOP mode
  lyra-launch-bridge            Launch bridge node only
  lyra-launch-rviz              Launch RViz visualization

CONTROL COMMANDS:
  lyra-arm                      ARM the robot (requires service)
  lyra-disarm                   DISARM the robot
  lyra-stop                     EMERGENCY STOP
  lyra-ros-mode-on              Enable ROS mode on STM32
  lyra-ros-mode-off             Disable ROS mode on STM32

MONITORING COMMANDS (use --once for single reading):
  lyra-status                   Show quick status overview
  lyra-battery [--once]         Monitor battery voltage
  lyra-armed-status [--once]    Monitor armed status
  lyra-wheel-rpm [--once]       Monitor wheel RPM
  lyra-wheel-ticks [--once]     Monitor wheel ticks
  lyra-imu [--once]             Monitor IMU data
  lyra-odom [--once]            Monitor odometry
  lyra-scan [--once]            Monitor LiDAR scans
  lyra-diagnostics [--once]     Monitor system diagnostics
  lyra-tf-tree                  Display TF tree visualization

NODE MANAGEMENT:
  lyra-nodes                    List all active nodes
  lyra-topics                   List all active topics
  lyra-services                 List all Lyra services
  lyra-node-info <name>         Show detailed node info

PARAMETER COMMANDS:
  lyra-params <node>            List node parameters
  lyra-param-get <node> <param> Get parameter value
  lyra-param-set <node> <param> <val>  Set parameter value

LOGGING & DEBUGGING:
  lyra-log-bridge               Show recent bridge logs
  lyra-log-live <node>          Live log viewer
  lyra-debug-bridge             Show detailed bridge diagnostics

CLEANUP & KILL:
  lyra-kill                     Kill all Lyra nodes (safe)
  lyra-kill-all                 Kill ALL ROS 2 nodes (careful!)
  lyra-cleanup                  Clean up ROS temp files
  lyra-reset                    Full system reset

TESTING:
  lyra-test-hardware            Test hardware connectivity
  lyra-test-connectivity        Test ROS network

HELP:
  lyra-help                     Show this help message
  lyra-commands                 List all available commands

QUICK START EXAMPLES:
  # Basic teleoperation
  $ lyra-launch-robot-teleop
  $ lyra-arm
  (use joystick deadman + sticks)
  $ lyra-disarm

  # SLAM mapping
  $ lyra-launch-robot-slam
  $ lyra-arm
  (drive around to build map)
  $ ros2 run nav2_map_server map_saver_cli -f ~/maps/my_map

  # Navigation with pre-built map
  $ lyra-launch-robot-nav ~/maps/my_map.yaml
  $ lyra-arm
  (click navigation goal in RViz)

  # Debugging
  $ lyra-status                 # Quick health check
  $ lyra-test-hardware          # Hardware connectivity test
  $ lyra-debug-bridge           # Detailed bridge info
  $ lyra-battery                # Watch battery voltage

TROUBLESHOOTING:
  Robot won't arm?
    → Check battery voltage: lyra-battery
    → Check bridge status: lyra-debug-bridge
    → Check joystick connection: lyra-test-hardware

  No topics appearing?
    → Check nodes are running: lyra-nodes
    → Check connectivity: lyra-test-connectivity
    → Check logs: lyra-log-bridge

  Serial connection issues?
    → Check port exists: ls -la /dev/ttyAMA0
    → Check permissions: groups
    → Try: sudo usermod -a -G dialout $USER

  Need to restart everything?
    → lyra-reset (nuclear option)

EOF
}

lyra-commands() {
    lyra_print_header "Available Commands"
    echo ""
    declare -F | grep "lyra-" | awk '{print "  " $3}' | sort
    echo ""
    echo "Run 'lyra-help' for detailed information"
}

# ============================================================================
# AUTO-COMPLETION SETUP (optional)
# ============================================================================

lyra-setup-completion() {
    lyra_print_header "Setting up auto-completion..."
    
    # Get all lyra functions
    local functions=$(declare -F | grep "lyra-" | awk '{print $3}' | sort)
    
    # Create completion function
    _lyra_completion() {
        local cur="${COMP_WORDS[COMP_CWORD]}"
        local commands="arm disarm stop battery status nodes topics services \
                       launch-base launch-robot-slam launch-robot-nav launch-robot-teleop \
                       test-hardware test-connectivity kill kill-all cleanup reset help commands"
        COMPREPLY=( $(compgen -W "$commands" -- "$cur") )
    }
    
    complete -F _lyra_completion lyra
    lyra_print_success "Auto-completion enabled (in current session)"
}

# ============================================================================
# INITIALIZATION
# ============================================================================

# Print welcome message
lyra_print_header "Lyra Robot Command Utility Loaded"
echo "Type 'lyra-help' for available commands"
echo "Type 'lyra-commands' for quick command list"
