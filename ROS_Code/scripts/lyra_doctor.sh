#!/bin/bash
#
# Lyra Robot Diagnostic and Self-Heal Script
# Automatically detects and attempts to fix common issues
#
# Usage: ./lyra_doctor.sh [--verbose] [--fix]
#

# NOTE: Do NOT use 'set -o errexit' - the counter increments ((COUNT++)) 
# return non-zero when count is 0, causing premature exit

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Flags
VERBOSE=false
AUTO_FIX=false
ERROR_COUNT=0
WARNING_COUNT=0
INFO_COUNT=0

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --verbose) VERBOSE=true; shift ;;
        --fix) AUTO_FIX=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Utility functions
print_header() {
    echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
    ((ERROR_COUNT++))
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
    ((WARNING_COUNT++))
}

print_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_info() {
    echo -e "${CYAN}[INFO]${NC} $1"
    ((INFO_COUNT++))
}

print_verbose() {
    if [ "$VERBOSE" = true ]; then
        echo -e "${CYAN}[DEBUG]${NC} $1"
    fi
}

print_recommendation() {
    echo -e "${YELLOW}[FIX]${NC} $1"
}

# ============================================================================
# CHECKS
# ============================================================================

check_ros_installation() {
    print_header "Checking ROS 2 Installation"
    
    if ! command -v ros2 &> /dev/null; then
        print_error "ROS 2 not found in PATH"
        print_recommendation "Source your ROS 2 setup: source /opt/ros/\$ROS_DISTRO/setup.bash"
        return 1
    fi
    
    local ros_distro=$(ros2 --version 2>&1 | grep -oP 'ros2.*' | head -1)
    print_success "ROS 2 installed: $ros_distro"
    
    if [ -z "$ROS_DISTRO" ]; then
        print_warning "ROS_DISTRO not set"
        print_recommendation "Source setup.bash: source /opt/ros/\$ROS_DISTRO/setup.bash"
    fi
    
    return 0
}

check_workspace() {
    print_header "Checking Workspace"
    
    local ws_dir="${HOME}/lyra_ws"
    
    if [ ! -d "$ws_dir" ]; then
        print_warning "Workspace not found at $ws_dir"
        return 1
    fi
    
    print_success "Workspace found: $ws_dir"
    
    # Check if it's been built
    if [ ! -d "$ws_dir/install" ]; then
        print_warning "Workspace not built"
        print_recommendation "Build workspace: cd $ws_dir && colcon build"
        return 1
    fi
    
    print_success "Workspace built"
    
    # Check if setup files exist
    if [ ! -f "$ws_dir/install/setup.bash" ]; then
        print_warning "Setup files not found"
        print_recommendation "Source workspace: source $ws_dir/install/setup.bash"
        return 1
    fi
    
    print_success "Setup files present"
    return 0
}

check_serial_connection() {
    print_header "Checking Serial Port Connection"
    
    local port="/dev/ttyAMA0"
    
    if [ ! -c "$port" ]; then
        print_error "Serial port $port not found"
        print_recommendation "Check GPIO UART pins (14/15) are connected"
        return 1
    fi
    
    print_success "Serial port exists: $port"
    
    # Check permissions
    if [ ! -r "$port" ] || [ ! -w "$port" ]; then
        print_warning "No read/write permissions on $port"
        print_recommendation "Fix permissions: sudo chmod 666 $port"
        
        if [ "$AUTO_FIX" = true ]; then
            print_info "Attempting to fix permissions..."
            sudo chmod 666 "$port" && print_success "Permissions fixed"
        fi
        return 1
    fi
    
    print_success "Serial port is readable and writable"
    
    # Check if it's in use
    if lsof "$port" &>/dev/null 2>&1; then
        local process=$(lsof "$port" 2>/dev/null | tail -1 | awk '{print $1}')
        print_info "Serial port in use by: $process"
    fi
    
    return 0
}

check_joystick() {
    print_header "Checking Joystick"
    
    if [ ! -c "/dev/input/js0" ]; then
        print_warning "No joystick found at /dev/input/js0"
        print_recommendation "Connect joystick via USB and verify: ls /dev/input/js*"
        return 1
    fi
    
    print_success "Joystick found: /dev/input/js0"
    
    # Check permissions
    if [ ! -r "/dev/input/js0" ]; then
        print_warning "Cannot read joystick device"
        print_recommendation "Add user to input group: sudo usermod -a -G input \$USER"
        return 1
    fi
    
    print_success "Joystick is readable"
    return 0
}

check_camera() {
    print_header "Checking Camera"
    
    if [ ! -c "/dev/video0" ]; then
        print_warning "No camera found"
        print_recommendation "Enable camera in raspi-config: sudo raspi-config"
        return 1
    fi
    
    print_success "Camera device found: /dev/video0"
    
    # Check if it's accessible
    if [ ! -r "/dev/video0" ]; then
        print_warning "Cannot read camera device"
        print_recommendation "Check camera ribbon cable connection"
        return 1
    fi
    
    print_success "Camera is accessible"
    return 0
}

check_ros_network() {
    print_header "Checking ROS 2 Network"
    
    # Check if we can discover nodes (this is the real test)
    if ! timeout 5 ros2 node list &>/dev/null; then
        print_warning "Cannot discover nodes (ROS network not initialized)"
        
        # Only check daemon if node discovery fails
        if ! ros2 daemon ping &>/dev/null 2>&1; then
            print_warning "ROS daemon not responding"
            print_recommendation "Restart daemon: ros2 daemon stop && ros2 daemon start"
            
            if [ "$AUTO_FIX" = true ]; then
                print_info "Restarting ROS daemon..."
                ros2 daemon stop 2>/dev/null || true
                sleep 1
                ros2 daemon start 2>/dev/null || true
                print_success "ROS daemon restarted"
            fi
        fi
        return 1
    fi
    
    print_success "ROS network operational"
    return 0
}

check_running_nodes() {
    print_header "Checking Active Nodes"
    
    local nodes=$(ros2 node list 2>/dev/null | wc -l)
    
    if [ "$nodes" -eq 0 ]; then
        print_warning "No ROS nodes are running"
        print_recommendation "Start robot: lyra-launch-robot-teleop"
        return 1
    fi
    
    print_success "$nodes nodes are running"
    
    # Check for critical nodes
    local critical_nodes=("lyra_bridge" "cmd_vel_gate" "joy_node")
    
    for node in "${critical_nodes[@]}"; do
        if ros2 node list 2>/dev/null | grep -q "$node"; then
            print_success "Found node: $node"
        else
            print_warning "Missing node: $node"
        fi
    done
    
    return 0
}

check_bridge_health() {
    print_header "Checking Bridge Node Health"
    
    # Check if bridge is running
    if ! ros2 node list 2>/dev/null | grep -q "lyra_bridge"; then
        print_warning "Bridge node not running"
        return 1
    fi
    
    print_success "Bridge node is running"
    
    # Check if bridge services exist (don't call arm - that would arm the robot!)
    if ! timeout 5 ros2 service list 2>/dev/null | grep -q "/lyra/arm"; then
        print_error "Bridge services not available"
        print_recommendation "Bridge may be hung or unresponsive"
        return 1
    fi
    
    print_success "Bridge services are available"
    return 0
}

check_telemetry_flow() {
    print_header "Checking Telemetry Data Flow"
    
    # Check battery voltage topic
    if ! timeout 5 ros2 topic echo /battery_voltage --once &>/dev/null 2>&1; then
        print_warning "Battery voltage topic not publishing"
        print_recommendation "Check STM32 connection and telemetry rate"
        return 1
    fi
    
    print_success "Battery voltage topic is publishing"
    
    # Check wheel RPM topic
    if ! timeout 5 ros2 topic echo /wheel_rpm --once &>/dev/null 2>&1; then
        print_warning "Wheel RPM topic not publishing"
        return 1
    fi
    
    print_success "Wheel RPM topic is publishing"
    
    # Check armed status topic
    if ! timeout 5 ros2 topic echo /lyra/armed --once &>/dev/null 2>&1; then
        print_warning "Armed status topic not publishing"
        return 1
    fi
    
    print_success "Armed status topic is publishing"
    
    return 0
}

check_battery_level() {
    print_header "Checking Battery Level"
    
    local voltage=$(timeout 5 ros2 topic echo /battery_voltage --once 2>/dev/null | grep "data:" | awk '{print $2}')
    
    if [ -z "$voltage" ]; then
        print_warning "Could not read battery voltage"
        return 1
    fi
    
    print_info "Battery voltage: ${voltage}V"
    
    # Check if battery is low
    if (( $(echo "$voltage < 10.0" | bc -l) )); then
        print_error "Battery is critically low (${voltage}V < 10.0V)"
        print_recommendation "Charge the battery immediately"
        return 1
    fi
    
    if (( $(echo "$voltage < 11.0" | bc -l) )); then
        print_warning "Battery is getting low (${voltage}V < 11.0V)"
        return 1
    fi
    
    print_success "Battery level is good (${voltage}V)"
    return 0
}

check_odometry() {
    print_header "Checking Odometry System"
    
    # Check wheel ticks
    if ! timeout 5 ros2 topic echo /wheel_ticks --once &>/dev/null 2>&1; then
        print_error "Wheel ticks not publishing"
        print_recommendation "Check encoder connections to STM32"
        return 1
    fi
    
    print_success "Wheel ticks are publishing"
    
    # Check wheel odometry node
    if ros2 node list 2>/dev/null | grep -q "wheel_odometry"; then
        print_success "Wheel odometry node is running"
    else
        print_warning "Wheel odometry node not running"
    fi
    
    # Check EKF
    if ros2 node list 2>/dev/null | grep -q "ekf_filter_node"; then
        print_success "EKF node is running"
    else
        print_warning "EKF node not running"
        return 1
    fi
    
    return 0
}

check_imu() {
    print_header "Checking IMU Sensor"
    
    # Check if IMU topic exists
    if ! timeout 5 ros2 topic echo /imu/data_raw --once &>/dev/null 2>&1; then
        print_warning "IMU topic not publishing"
        print_recommendation "Check IMU is enabled in launch parameters"
        return 1
    fi
    
    print_success "IMU is publishing data"
    return 0
}

check_lidar() {
    print_header "Checking LiDAR"
    
    # Check scan topic
    if ! timeout 5 ros2 topic echo /scan --once &>/dev/null 2>&1; then
        print_warning "LiDAR scans not publishing"
        print_recommendation "Check LiDAR USB connection and power"
        return 1
    fi
    
    print_success "LiDAR is publishing scans"
    
    # Check scan frequency
    local freq=$(timeout 5 ros2 topic hz /scan 2>&1 | grep "average frequency" | awk '{print $3}')
    
    if [ -z "$freq" ]; then
        print_warning "Could not determine scan frequency"
    else
        print_info "LiDAR frequency: ${freq}Hz"
    fi
    
    return 0
}

check_disk_space() {
    print_header "Checking Disk Space"
    
    # Check root filesystem
    local usage=$(df / | tail -1 | awk '{print $5}' | sed 's/%//')
    
    print_info "Root filesystem usage: ${usage}%"
    
    if [ "$usage" -gt 90 ]; then
        print_error "Disk almost full (${usage}%)"
        print_recommendation "Clean up old log files: rm -rf ~/.ros/log/*"
        return 1
    fi
    
    if [ "$usage" -gt 80 ]; then
        print_warning "Disk usage is high (${usage}%)"
        return 1
    fi
    
    print_success "Disk space is good (${usage}%)"
    return 0
}

check_memory() {
    print_header "Checking Memory"
    
    local total=$(free -h | grep "^Mem:" | awk '{print $2}')
    local used=$(free -h | grep "^Mem:" | awk '{print $3}')
    local percent=$(free | grep "^Mem:" | awk '{printf "%.0f", $3/$2*100}')
    
    print_info "Memory usage: $used / $total (${percent}%)"
    
    if [ "$percent" -gt 90 ]; then
        print_error "Memory almost full (${percent}%)"
        print_recommendation "Kill unused processes or reboot"
        return 1
    fi
    
    if [ "$percent" -gt 75 ]; then
        print_warning "Memory usage is high (${percent}%)"
        return 1
    fi
    
    print_success "Memory usage is good (${percent}%)"
    return 0
}

check_cpu_temp() {
    print_header "Checking CPU Temperature"
    
    if ! command -v vcgencmd &> /dev/null; then
        print_verbose "vcgencmd not available (not on RPi)"
        return 0
    fi
    
    local temp=$(vcgencmd measure_temp 2>/dev/null | grep -oP '\d+\.\d+' | cut -d. -f1)
    
    if [ -z "$temp" ]; then
        print_verbose "Could not read CPU temperature"
        return 0
    fi
    
    print_info "CPU temperature: ${temp}°C"
    
    if [ "$temp" -gt 80 ]; then
        print_error "CPU is overheating (${temp}°C > 80°C)"
        print_recommendation "Improve airflow or throttle CPU"
        return 1
    fi
    
    if [ "$temp" -gt 70 ]; then
        print_warning "CPU is getting warm (${temp}°C)"
        return 1
    fi
    
    print_success "CPU temperature is normal (${temp}°C)"
    return 0
}

check_network_interfaces() {
    print_header "Checking Network Interfaces"
    
    # Check ethernet
    if ip link show eth0 2>/dev/null | grep -q "state UP"; then
        print_success "Ethernet connected"
    elif ip link show eth0 2>/dev/null | grep -q "state DOWN"; then
        print_warning "Ethernet disconnected"
    else
        print_verbose "No ethernet interface"
    fi
    
    # Check WiFi
    if ip link show wlan0 2>/dev/null | grep -q "state UP"; then
        print_success "WiFi connected"
    elif ip link show wlan0 2>/dev/null | grep -q "state DOWN"; then
        print_warning "WiFi disconnected"
    else
        print_verbose "No WiFi interface"
    fi
    
    return 0
}

# ============================================================================
# MAIN DIAGNOSTIC ROUTINE
# ============================================================================

run_diagnostics() {
    print_header "LYRA ROBOT DIAGNOSTIC REPORT"
    echo "Generated: $(date)"
    echo "Verbose: $VERBOSE | Auto-Fix: $AUTO_FIX"
    echo ""
    
    # System checks
    check_ros_installation || true
    check_workspace || true
    check_network_interfaces || true
    check_disk_space || true
    check_memory || true
    check_cpu_temp || true
    
    echo ""
    
    # Hardware checks
    check_serial_connection || true
    check_joystick || true
    check_camera || true
    
    echo ""
    
    # ROS checks
    check_ros_network || true
    check_running_nodes || true
    
    echo ""
    
    # Robot health checks
    if ros2 node list 2>/dev/null | grep -q "lyra_bridge"; then
        check_bridge_health || true
        check_telemetry_flow || true
        check_battery_level || true
        check_odometry || true
        check_imu || true
        check_lidar || true
    else
        print_info "Bridge not running - skipping bridge health checks"
    fi
    
    echo ""
}

# ============================================================================
# SUMMARY
# ============================================================================

print_summary() {
    print_header "DIAGNOSTIC SUMMARY"
    
    local total=$((ERROR_COUNT + WARNING_COUNT + INFO_COUNT))
    
    echo "Errors:   $ERROR_COUNT"
    echo "Warnings: $WARNING_COUNT"
    echo "Info:     $INFO_COUNT"
    echo "Total:    $total"
    echo ""
    
    if [ "$ERROR_COUNT" -gt 0 ]; then
        echo -e "${RED}Status: CRITICAL - Fix errors before operating robot${NC}"
        return 1
    elif [ "$WARNING_COUNT" -gt 0 ]; then
        echo -e "${YELLOW}Status: WARNING - Some issues detected, review recommendations${NC}"
        return 1
    else
        echo -e "${GREEN}Status: OK - System is ready${NC}"
        return 0
    fi
}

# ============================================================================
# MAIN
# ============================================================================

main() {
    echo ""
    run_diagnostics
    echo ""
    print_summary
}

main
