// Core/Src/app/lyra_proto.c

#include "app/lyra_proto.h"
#include "app/lyra_cmd.h"
#include "config/robot_config.h"
#include "app/debug_log.h"
#include "app/config_storage.h"
#include "app/app_main.h"
#include <string.h>
#include <stdio.h>
#include "cmsis_os.h"
#include "usbd_cdc_if.h"  // For USB_Send
#include "stm32f4xx_hal.h"  // For HAL_GetTick
#include "usart.h"  // For huart3
#include "drivers/encoder_driver.h"   // Encoder_GetRPM, Encoder_GetTotalTicks
#include "drivers/adc_utils.h"       // ADC_Utils_GetBatteryVoltage
#include "drivers/motor_driver.h"    // MotorStatus_t
#include "drivers/imu_lsm6dsrtr.h"   // imu_sample_t (if not included elsewhere)

/* Build status bitfield:
   bit0 = system armed
   bits 1..4 = per-motor fault indicator (1 = fault)
*/
static uint16_t build_status_flags(void)
{
    extern uint8_t volatile system_armed;          // declared in app_main.c
    extern MotorStatus_t motor_status[5]; // declared in app_main.c

    uint16_t flags = 0;
    if (system_armed) flags |= 0x0001;

    for (int m = MOTOR_1; m <= MOTOR_4; m++) {
        if (motor_status[m].fault_count > 0) {
            flags |= (1u << m);
        }
    }
    return flags;
}

/* Ensure we can reference current IMU sample if not visible via headers */
extern imu_sample_t current_imu_data;
extern uint8_t volatile ros_mode_enabled;  // From app_main.c

// ====================== CRC16-CCITT ==========================
//
// Params:
//   data: pointer to bytes
//   len : number of bytes
//
// Polynomial: 0x1021
// Init value: 0xFFFF
//
// We compute CRC over: [seq, cmd, length, payload...]
//
uint16_t lyra_proto_crc16(const uint8_t *data, size_t len)
{
    uint16_t crc = 0xFFFF;

    for (size_t i = 0; i < len; i++) {
        crc ^= ((uint16_t)data[i] << 8);
        for (int bit = 0; bit < 8; bit++) {
            if (crc & 0x8000) {
                crc = (uint16_t)((crc << 1) ^ 0x1021);
            } else {
                crc <<= 1;
            }
        }
    }
    return crc;
}

// ====================== Parser init ==========================

void lyra_proto_parser_init(LyraProtoParser_t *p)
{
    if (!p) return;
    p->idx          = 0;
    p->expected_len = 0;
    p->in_frame     = false;
}

// ====================== Parser feed ==========================
//
// Feed one byte at a time.
// Returns true when a full, CRC-valid packet is decoded into out_pkt.
//
// Important: this is a simple "sync on 0xAA" parser.
// If anything invalid happens (bad header2, too long, CRC fail), we reset.
//

bool lyra_proto_parser_feed(LyraProtoParser_t *p, uint8_t byte, LyraProtoPacket_t *out_pkt)
{
    if (!p || !out_pkt) {
        return false;
    }

    // Not currently in a frame: look for header1
    if (!p->in_frame) {
        if (byte == LYRA_PROTO_HDR1) {
            p->in_frame = true;
            p->idx      = 0;
            p->buf[p->idx++] = byte;  // store header1 at [0]
        }
        // ignore everything else
        return false;
    }

    // We are inside a frame
    if (p->idx >= sizeof(p->buf)) {
        // Buffer overflow — reset state
        p->in_frame = false;
        p->idx      = 0;
        p->expected_len = 0;
        return false;
    }

    p->buf[p->idx++] = byte;

    // Check header2 (position 1)
    if (p->idx == 2) {
        if (byte != LYRA_PROTO_HDR2) {
            // Wrong header2 → reset and wait for next 0xAA
            p->in_frame = false;
            p->idx      = 0;
            p->expected_len = 0;
        }
        return false;
    }

    // Once we have header1, header2, seq, cmd, len → idx == 5
    if (p->idx == 5) {
        uint8_t len = p->buf[4];  // length byte
        if (len > LYRA_PROTO_MAX_PAYLOAD) {
            // Invalid length, reset
            p->in_frame = false;
            p->idx      = 0;
            p->expected_len = 0;
            return false;
        }
        p->expected_len = len;
        return false;
    }

    // We know length; full frame size in bytes is:
    //  2 (hdr) + 1 (seq) + 1 (cmd) + 1 (len) + N (payload) + 2 (crc)
    //  = 7 + N
    //
    // Since idx is the count of bytes stored so far (starting from 1),
    // when idx == 7 + expected_len, we have the whole frame.
    //
    uint8_t needed = (uint8_t)(7 + p->expected_len);
    if (p->idx == needed) {

        // Extract fields
        uint8_t header1 = p->buf[0];
        uint8_t header2 = p->buf[1];
        uint8_t seq     = p->buf[2];
        uint8_t cmd     = p->buf[3];
        uint8_t length  = p->buf[4];

        // Payload starts at index 5
        const uint8_t *payload = &p->buf[5];

        // CRC bytes
        uint8_t crc_lo = p->buf[5 + length];
        uint8_t crc_hi = p->buf[5 + length + 1];
        uint16_t crc_wire = (uint16_t)crc_lo | ((uint16_t)crc_hi << 8);

        // Calculate expected CRC over [seq, cmd, length, payload...]
        uint16_t crc_calc = lyra_proto_crc16(&p->buf[2], (size_t)(3 + length));

        bool ok = (crc_wire == crc_calc);

        // Reset parser state now (whether ok or not)
        p->in_frame     = false;
        p->idx          = 0;
        p->expected_len = 0;

        if (!ok) {
            // CRC mismatch → drop
            return false;
        }

        // Fill out packet struct
        out_pkt->header1 = header1;
        out_pkt->header2 = header2;
        out_pkt->seq     = seq;
        out_pkt->cmd     = cmd;
        out_pkt->length  = length;

        // Copy payload if any
        if (length > 0) {
            memcpy(out_pkt->payload, payload, length);
        }

        out_pkt->crc = crc_wire;

        return true;  // One full, valid packet decoded
    }

    // Not enough bytes yet
    return false;
}

// ---------------------------------------------------------------------------
//  Binary protocol command handler
// ---------------------------------------------------------------------------
void lyra_proto_handle_packet(const LyraProtoPacket_t *pkt)
{
    if (!pkt) return;

    uint8_t cmd = pkt->cmd;
    uint8_t len = pkt->length;
    const uint8_t *pl = pkt->payload;

    switch (cmd)
    {
        case LYRA_CMD_ARM:
            lyra_cmd_arm();
            break;

        case LYRA_CMD_DISARM:
            lyra_cmd_disarm();
            break;

        case LYRA_CMD_EMERGENCY_STOP:
            lyra_cmd_stop();
            system_armed = 0;
            LOGE("CMD: EMERGENCY_STOP -> DISARMED");
            break;

        case LYRA_CMD_SET_WHEEL_VEL:
        {
            // Payload: 4 x float32, wheel angular velocities in rad/s: [w1,w2,w3,w4]
            if (pkt->length < 4 * sizeof(float)) {
            	LOGE("PROTO: SET_WHEEL_VEL payload too short");
                return;
            }

            float w_rad_s[4];
            memcpy(&w_rad_s[0], &pkt->payload[0 * sizeof(float)], sizeof(float));
            memcpy(&w_rad_s[1], &pkt->payload[1 * sizeof(float)], sizeof(float));
            memcpy(&w_rad_s[2], &pkt->payload[2 * sizeof(float)], sizeof(float));
            memcpy(&w_rad_s[3], &pkt->payload[3 * sizeof(float)], sizeof(float));

            lyra_cmd_set_wheel_vel_rad_s(w_rad_s);
            break;
        }

        case LYRA_CMD_SET_PID:
            if (len != (1 + sizeof(float) * 3)) {
            	LOGE("ERR: SET_PID bad length %u", len);
                break;
            } else {
                uint8_t idx = pl[0];
                float kp, ki, kd;
                memcpy(&kp, pl + 1, sizeof(float));
                memcpy(&ki, pl + 5, sizeof(float));
                memcpy(&kd, pl + 9, sizeof(float));
                lyra_cmd_set_pid(idx, kp, ki, kd);
            }
            break;

        case LYRA_CMD_SAVE_CONFIG:
        	config_request_save();
            break;

        case LYRA_CMD_LOAD_CONFIG:
            config_init();
            config_print();
            break;

        case LYRA_CMD_GET_TELEMETRY:
            lyra_proto_send_telemetry(pkt->seq);
            break;

        case LYRA_CMD_HEARTBEAT:
            last_cmd_ms = HAL_GetTick();
            break;

        case LYRA_CMD_SET_ROS_MODE:
            if (pkt->length < 1) {
            	LOGE("PROTO: SET_ROS_MODE payload too short");
                return;
            }
            lyra_cmd_set_ros_mode(pkt->payload[0] ? 1 : 0);
            break;

        default:
        	LOGW("ERR: Unknown binary cmd 0x%02X", cmd);
            break;
    }
}


// ===== PACKET SEND FUNCTION (Thread-Safe with Static Buffer) =====

// Static send buffer (eliminates stack allocation)
static uint8_t tx_buffer[LYRA_PROTO_MAX_PAYLOAD + 8];
static osMutexId_t tx_mutex = NULL;

// Call this once during app_init()
void lyra_proto_init_tx(void)
{
    if (tx_mutex == NULL) {
        const osMutexAttr_t tx_mutex_attr = {
            .name = "LyraTX",
            .attr_bits = osMutexRecursive | osMutexPrioInherit,
        };
        tx_mutex = osMutexNew(&tx_mutex_attr);
    }
}

// Thread-safe packet send with static buffer
void lyra_proto_send_packet(uint8_t cmd, const uint8_t *payload, uint8_t len)
{
    if (len > LYRA_PROTO_MAX_PAYLOAD) {
        return;  // Payload too large
    }

    // Acquire mutex (wait max 50ms)
    if (tx_mutex == NULL || osMutexAcquire(tx_mutex, 50) != osOK) {
        return;  // Failed to acquire lock
    }

    uint8_t idx = 0;

    // Header
    tx_buffer[idx++] = LYRA_PROTO_HDR1;  // 0xAA
    tx_buffer[idx++] = LYRA_PROTO_HDR2;  // 0x55

    // Sequence (use timestamp LSB)
    tx_buffer[idx++] = (uint8_t)(HAL_GetTick() & 0xFF);

    // Command & Length
    tx_buffer[idx++] = cmd;
    tx_buffer[idx++] = len;

    // Payload
    if (len > 0 && payload != NULL) {
        memcpy(&tx_buffer[idx], payload, len);
        idx += len;
    }

    // CRC16 over seq, cmd, length, payload
    uint16_t crc = lyra_proto_crc16(&tx_buffer[2], idx - 2);
    tx_buffer[idx++] = (uint8_t)(crc & 0xFF);
    tx_buffer[idx++] = (uint8_t)(crc >> 8);

    // ✅ PRODUCTION: Send based on global transport config
    switch (g_transport_target) {
        case TRANSPORT_USB:
            USB_Send(tx_buffer, idx);
            break;

        case TRANSPORT_UART3:
            HAL_UART_Transmit(&huart3, tx_buffer, idx, 100);
            break;

        case TRANSPORT_BOTH:
            USB_Send(tx_buffer, idx);
            HAL_UART_Transmit(&huart3, tx_buffer, idx, 100);
            break;

        default:
            // Fallback to USB
            USB_Send(tx_buffer, idx);
            break;
    }

    // Release mutex
    osMutexRelease(tx_mutex);
}

// ---------------------------------------------------------------------------
//  SEND TELEMETRY (Binary "LYRT" frame)
// ---------------------------------------------------------------------------
void lyra_proto_send_telemetry(uint8_t seq)
{
    extern imu_sample_t current_imu_data;
    extern uint8_t volatile system_armed;
    extern MotorStatus_t motor_status[5];

    lyra_telemetry_t t;
    memset(&t, 0, sizeof(t));

    t.timestamp_ms = HAL_GetTick();

    for (int i = 0; i < 4; i++) {
        t.wheel_rpm[i]   = Encoder_GetRPM((MotorID_t)(i + 1));
        t.wheel_ticks[i] = (int32_t)Encoder_GetTotalTicks((MotorID_t)(i + 1));
    }

    // Status flags
    t.status_flags = build_status_flags();

    t.battery_v = ADC_Utils_GetBatteryVoltage();
    t.accel_x   = current_imu_data.ax_g;
    t.accel_y   = current_imu_data.ay_g;
    t.accel_z   = current_imu_data.az_g;
    t.gyro_x    = current_imu_data.gx_dps;
    t.gyro_y    = current_imu_data.gy_dps;
    t.gyro_z    = current_imu_data.gz_dps;

    // Build payload with 4-byte "LYRT" prefix
    const uint8_t magic[4] = {'L','Y','R','T'};
    uint8_t payload[4 + sizeof(t)];
    memcpy(payload, magic, 4);
    memcpy(payload + 4, &t, sizeof(t));

    // Compose full frame
    uint8_t frame[5 + sizeof(payload) + 2];
    uint8_t idx = 0;

    frame[idx++] = LYRA_PROTO_HDR1;
    frame[idx++] = LYRA_PROTO_HDR2;
    frame[idx++] = seq;
    frame[idx++] = LYRA_CMD_GET_TELEMETRY;
    frame[idx++] = sizeof(payload);
    memcpy(&frame[idx], payload, sizeof(payload));
    idx += sizeof(payload);

    uint16_t crc = lyra_proto_crc16(&frame[2], 3 + sizeof(payload));
    frame[idx++] = (uint8_t)(crc & 0xFF);
    frame[idx++] = (uint8_t)(crc >> 8);

    switch (g_transport_target) {
        case TRANSPORT_USB:
            USB_Send(frame, idx);
            break;
        case TRANSPORT_UART3:
            HAL_UART_Transmit(&huart3, frame, idx, 200);
            break;
        case TRANSPORT_BOTH:
            USB_Send(frame, idx);
            HAL_UART_Transmit(&huart3, frame, idx, 200);
            break;
        default:
            USB_Send(frame, idx);
            break;
    }
}
