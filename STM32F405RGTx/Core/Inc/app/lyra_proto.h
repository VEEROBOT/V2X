#ifndef LYRA_PROTO_H
#define LYRA_PROTO_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

// Constants
#define LYRA_PROTO_HDR1       0xAA
#define LYRA_PROTO_HDR2       0x55
#define LYRA_PROTO_MAX_PAYLOAD 32

typedef enum {
    LYRA_CMD_ARM            = 0x80,
    LYRA_CMD_DISARM         = 0x81,
    LYRA_CMD_SET_WHEEL_VEL  = 0x82,
    LYRA_CMD_SET_RC_MODE    = 0x83,
    LYRA_CMD_SET_PID        = 0x84,
    LYRA_CMD_GET_TELEMETRY  = 0x85,
    LYRA_CMD_SAVE_CONFIG    = 0x86,
    LYRA_CMD_LOAD_CONFIG    = 0x87,
    LYRA_CMD_HEARTBEAT      = 0x88,
    LYRA_CMD_EMERGENCY_STOP = 0x89,
    LYRA_CMD_SET_ROS_MODE   = 0x8A,
} LyraProtoCmd_t;

typedef struct {
    uint8_t  header1;   // 0xAA
    uint8_t  header2;   // 0x55
    uint8_t  seq;
    uint8_t  cmd;
    uint8_t  length;    // bytes of payload
    uint8_t  payload[LYRA_PROTO_MAX_PAYLOAD];
    uint16_t crc;       // CCITT
} LyraProtoPacket_t;

// CRC + parser API
uint16_t lyra_proto_crc16(const uint8_t *data, size_t len);

// Incremental parser state
typedef struct {
    uint8_t  buf[LYRA_PROTO_MAX_PAYLOAD + 8];
    uint8_t  idx;
    uint8_t  expected_len;
    bool     in_frame;
} LyraProtoParser_t;

void lyra_proto_parser_init(LyraProtoParser_t *p);
void lyra_proto_send_telemetry(uint8_t seq);
bool lyra_proto_parser_feed(LyraProtoParser_t *p, uint8_t byte, LyraProtoPacket_t *out_pkt);
void lyra_proto_handle_packet(const LyraProtoPacket_t *pkt);

// ===== TELEMETRY MESSAGE IDs =====
#define LYRA_MSG_MOTOR_STATE       0x30
#define LYRA_MSG_IMU_DATA          0x31
#define LYRA_MSG_SYSTEM_STATUS     0x32

// Protocol version (increment when structure changes)
#define LYRA_PROTO_VERSION         0x01

// Motor state packet (44 bytes payload)
typedef struct __attribute__((packed)) {
    uint32_t timestamp_ms;
    float    wheel_rpm[4];
    int32_t  wheel_ticks[4];
    uint16_t status_flags;
    float    battery_v;
    float    accel_x;
    float    accel_y;
    float    accel_z;
    float    gyro_x;
    float    gyro_y;
    float    gyro_z;
} lyra_telemetry_t;

// IMU packet (28 bytes payload)
typedef struct __attribute__((packed)) {
    float accel[3];         // 12 bytes (m/s²)
    float gyro[3];          // 12 bytes (deg/s)
    uint32_t timestamp_ms;  // 4 bytes
} LyraIMUData_t;

// System status packet (25 bytes payload)
typedef struct __attribute__((packed)) {
    uint8_t protocol_version;  // 1 byte - LYRA_PROTO_VERSION
    uint32_t uptime_sec;       // 4 bytes
    uint32_t fault_count[4];   // 16 bytes
    uint8_t armed;             // 1 byte
    uint8_t control_mode;      // 1 byte
    uint8_t ros_mode;          // 1 byte
    uint8_t reserved;          // 1 byte (alignment)
} LyraSystemStatus_t;

// Thread-safe send functions
void lyra_proto_init_tx(void);
void lyra_proto_send_packet(uint8_t cmd, const uint8_t *payload, uint8_t len);

#endif
