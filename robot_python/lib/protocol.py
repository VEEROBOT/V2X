"""
Lyra Bridge - Binary Protocol Layer
Implements Lyra Protocol packet parsing and command building.

Frame format: [0xAA 0x55] [seq] [cmd] [len] [payload...] [CRC16-LE]
"""

import struct
from typing import Optional, Tuple


# Protocol constants
HDR1 = 0xAA
HDR2 = 0x55
MAX_PAYLOAD = 32

# Command opcodes (matches STM32 LyraProtoCmd_t)
CMD_ARM            = 0x80
CMD_DISARM         = 0x81
CMD_SET_WHEEL_VEL  = 0x82
CMD_SET_RC_MODE    = 0x83
CMD_SET_PID        = 0x84
CMD_GET_TELEMETRY  = 0x85
CMD_SAVE_CONFIG    = 0x86
CMD_LOAD_CONFIG    = 0x87
CMD_HEARTBEAT      = 0x88
CMD_EMERGENCY_STOP = 0x89
CMD_SET_ROS_MODE   = 0x8A


def crc16_ccitt(data: bytes) -> int:
    """
    Calculate CRC16-CCITT (polynomial 0x1021, init 0xFFFF).
    Matches STM32 implementation exactly.
    
    Args:
        data: Bytes to checksum
        
    Returns:
        16-bit CRC value
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= (byte << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


def build_frame(seq: int, cmd: int, payload: bytes = b'') -> bytes:
    """
    Build a complete Lyra protocol frame.
    
    Args:
        seq: Sequence number (0-255)
        cmd: Command opcode
        payload: Command payload bytes (max 32 bytes)
        
    Returns:
        Complete frame ready for transmission
    """
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"Payload too large: {len(payload)} > {MAX_PAYLOAD}")
    
    # Build frame body: [seq] [cmd] [len] [payload...]
    length = len(payload)
    body = bytes([seq, cmd, length]) + payload
    
    # Calculate CRC over body
    crc = crc16_ccitt(body)
    
    # Build complete frame: [HDR1 HDR2] [body] [CRC-LE]
    frame = bytes([HDR1, HDR2]) + body + struct.pack('<H', crc)
    
    return frame


def parse_from_buffer(buf: bytearray) -> Optional[Tuple[int, int, bytes]]:
    """
    Parse one packet from buffer (destructive - removes parsed data).
    
    Args:
        buf: Bytearray containing received data
        
    Returns:
        Tuple of (seq, cmd, payload) if valid packet found, None otherwise
    """
    # Need at least 7 bytes: [AA 55] [seq cmd len] [CRC16]
    if len(buf) < 7:
        return None
    
    # Check for header
    if buf[0] != HDR1 or buf[1] != HDR2:
        # Sync error - discard one byte and retry
        buf.pop(0)
        return None
    
    # Extract header fields
    seq = buf[2]
    cmd = buf[3]
    length = buf[4]
    
    # Total packet size
    total_len = 7 + length  # 2(hdr) + 3(seq/cmd/len) + length + 2(crc)
    
    # Wait for complete packet
    if len(buf) < total_len:
        return None
    
    # Extract payload and CRC
    payload = bytes(buf[5:5+length])
    crc_rx = struct.unpack('<H', buf[5+length:5+length+2])[0]
    
    # Calculate expected CRC (over seq/cmd/len/payload)
    body = buf[2:5+length]
    crc_calc = crc16_ccitt(body)
    
    # Remove parsed packet from buffer
    del buf[:total_len]
    
    # Validate CRC
    if crc_rx != crc_calc:
        # CRC mismatch - discard packet
        return None
    
    return (seq, cmd, payload)


# ============================================================================
# Command Builders
# ============================================================================

def build_arm_command(seq: int) -> bytes:
    """Build ARM command (0x80)."""
    return build_frame(seq, CMD_ARM, b'')


def build_disarm_command(seq: int) -> bytes:
    """Build DISARM command (0x81)."""
    return build_frame(seq, CMD_DISARM, b'')


def build_emergency_stop_command(seq: int) -> bytes:
    """Build EMERGENCY_STOP command (0x89)."""
    return build_frame(seq, CMD_EMERGENCY_STOP, b'')


def build_set_wheel_vel_command(seq: int, wheel_vels_rad_s: list) -> bytes:
    """
    Build SET_WHEEL_VEL command (0x82).
    
    Args:
        seq: Sequence number
        wheel_vels_rad_s: List of 4 floats [FL, RL, FR, RR] in rad/s
        
    Returns:
        Command frame
    """
    if len(wheel_vels_rad_s) != 4:
        raise ValueError("Need exactly 4 wheel velocities")
    
    # Pack as 4 x float32 (little-endian)
    payload = struct.pack('<4f', *wheel_vels_rad_s)
    return build_frame(seq, CMD_SET_WHEEL_VEL, payload)


def build_get_telemetry_command(seq: int) -> bytes:
    """Build GET_TELEMETRY command (0x85)."""
    return build_frame(seq, CMD_GET_TELEMETRY, b'')


def build_heartbeat_command(seq: int) -> bytes:
    """Build HEARTBEAT command (0x88)."""
    return build_frame(seq, CMD_HEARTBEAT, b'')


def build_set_ros_mode_command(seq: int, enable: bool) -> bytes:
    """
    Build SET_ROS_MODE command (0x8A).
    
    Args:
        seq: Sequence number
        enable: True to enable ROS mode (disable ASCII telemetry)
        
    Returns:
        Command frame
    """
    payload = bytes([1 if enable else 0])
    return build_frame(seq, CMD_SET_ROS_MODE, payload)


def build_set_pid_command(seq: int, motor_idx: int, kp: float, ki: float, kd: float) -> bytes:
    """
    Build SET_PID command (0x84).
    
    Args:
        seq: Sequence number
        motor_idx: Motor index (0-3 for M1-M4)
        kp, ki, kd: PID gains
        
    Returns:
        Command frame
    """
    # Payload: [motor_idx(u8)] [kp(f32)] [ki(f32)] [kd(f32)]
    payload = struct.pack('<B3f', motor_idx, kp, ki, kd)
    return build_frame(seq, CMD_SET_PID, payload)


def build_save_config_command(seq: int) -> bytes:
    """Build SAVE_CONFIG command (0x86)."""
    return build_frame(seq, CMD_SAVE_CONFIG, b'')


def build_load_config_command(seq: int) -> bytes:
    """Build LOAD_CONFIG command (0x87)."""
    return build_frame(seq, CMD_LOAD_CONFIG, b'')
