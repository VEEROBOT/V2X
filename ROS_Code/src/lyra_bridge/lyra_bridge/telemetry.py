"""
Lyra telemetry packet parser.
Handles the binary telemetry structure from STM32F405.

"""

import struct
import logging

logger = logging.getLogger(__name__)


# Telemetry structure format
# Structure (66 bytes total):
#   uint32_t timestamp_ms;     // 4 bytes
#   float    wheel_rpm[4];     // 16 bytes
#   int32_t  wheel_ticks[4];   // 16 bytes
#   uint16_t status_flags;     // 2 bytes
#   float    battery_v;        // 4 bytes
#   float    accel_x;          // 4 bytes
#   float    accel_y;          // 4 bytes
#   float    accel_z;          // 4 bytes
#   float    gyro_x;           // 4 bytes
#   float    gyro_y;           // 4 bytes
#   float    gyro_z;           // 4 bytes

STRUCT_FORMAT = '<I4f4iH7f'
STRUCT_SIZE =70
HEADER_SIZE = 4   # 'LYRT'

def parse_telemetry(payload: bytes) -> dict:
    # Expect full packet from STM32
    if len(payload) != STRUCT_SIZE:
        logger.warning(
            f"Telemetry size mismatch: got {len(payload)}, expected {STRUCT_SIZE}"
        )
        return None

    # Validate header
    if payload[0:4] != b'LYRT':
        logger.warning(f"Invalid telemetry header: {payload[0:4]}")
        return None

    # Strip header and unpack payload
    try:
        data = struct.unpack(STRUCT_FORMAT, payload[HEADER_SIZE:])
    except struct.error as e:
        logger.error(f"Failed to unpack telemetry: {e}")
        return None

    return {
        'timestamp_ms': data[0],
        'wheel_rpm': list(data[1:5]),
        'wheel_ticks': list(data[5:9]),
        'status_flags': data[9],
        'battery_v': data[10],
        'accel_x': data[11],
        'accel_y': data[12],
        'accel_z': data[13],
        'gyro_x': data[14],
        'gyro_y': data[15],
        'gyro_z': data[16],
    }

#    except struct.error as e:
#        logger.error(f"Failed to unpack telemetry: {e}")
#        return None


def parse_status_flags(status_flags: int) -> dict:
    """
    Extract individual status bits from flags.
    
    Bit mapping (from STM32):
        Bit 0: System armed
        Bit 1-4: Motor stall flags
        Bit 5-15: Reserved
    
    Args:
        status_flags: 16-bit status flags from telemetry
        
    Returns:
        Dictionary with parsed flags
    """
    return {
        'armed': bool(status_flags & 0x01),
        'motor1_stall': bool(status_flags & 0x02),
        'motor2_stall': bool(status_flags & 0x04),
        'motor3_stall': bool(status_flags & 0x08),
        'motor4_stall': bool(status_flags & 0x10),
    }
