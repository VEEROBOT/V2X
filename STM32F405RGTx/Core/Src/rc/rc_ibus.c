#include "rc/rc_ibus.h"
#include "app/lyra_cmd.h"
#include "usart.h"          // HAL UART handle
#include "app/app_main.h"   // for lyra_cmd_set_skid / system_armed
#include "app/app_transport.h"
#include "app/debug_log.h"
#include "app/config_storage.h"
#include <string.h>
#include <math.h>

IBUS_State_t ibus_state = {0};

volatile uint32_t ibus_rx_byte_count = 0;

// Debug: store last N raw bytes from UART5
uint8_t ibus_raw_buf[IBUS_RAW_BUF_SIZE];
uint8_t ibus_raw_index = 0;

uint8_t ibus_buf[IBUS_FRAME_SIZE];
static uint8_t ibus_index = 0;

void ibus_init(void)
{
    ibus_state.valid = false;
    ibus_state.last_update_ms = 0;

    // Enable UART RX interrupt
    HAL_UART_Receive_IT(&huart5, &ibus_buf[0], 1); // assuming USART5, change if needed
}

//void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
//{
//    if (huart->Instance == UART5) {
//        uint8_t b = ibus_buf[0];
//        ibus_on_byte(b);
//
//        // restart interrupt
//        HAL_UART_Receive_IT(&huart5, &ibus_buf[0], 1);
//    }
//}

void ibus_on_byte(uint8_t b)
{
    ibus_rx_byte_count++;  // count all bytes seen

    // Debug: log into circular raw buffer
    ibus_raw_buf[ibus_raw_index] = b;
    ibus_raw_index = (ibus_raw_index + 1) % IBUS_RAW_BUF_SIZE;

    if (ibus_index == 0 && b != 0x20) {
        return; // iBus frames always start with 0x20
    }

    ibus_buf[ibus_index++] = b;

    if (ibus_index >= IBUS_FRAME_SIZE) {
        ibus_process_frame(ibus_buf);
        ibus_index = 0;
    }
}

void ibus_process_frame(uint8_t *buf)
{
// remove this and recheck if RC is not working. CRC was creating issues with RC
    // Validate CRC first - reject garbage frames
    uint16_t sum = 0;
    for (int i = 0; i < IBUS_FRAME_SIZE - 2; i++) {
        sum += buf[i];
    }
    uint16_t crc_received = buf[IBUS_FRAME_SIZE - 2] | (buf[IBUS_FRAME_SIZE - 1] << 8);
    uint16_t crc_expected = 0xFFFF - sum;

    if (crc_received != crc_expected) {
        // Garbage frame - reset and wait for next real frame
        return;
    }

// remove till here and recheck

    // Decode up to IBUS_MAX_CHANNELS channels
    for (int i = 0; i < IBUS_MAX_CHANNELS; i++) {
        int offset = 2 + 2 * i;

        // Stop if we would read beyond the known frame size
        if (offset + 1 >= IBUS_FRAME_SIZE - 2) {
            break;
        }

        uint16_t raw = buf[offset] | (buf[offset + 1] << 8);

        // Store raw value
        ibus_state.raw[i] = raw;

        // Normalize 1000–2000 us → -1..+1
        float norm = (raw - 1500.0f) / 500.0f;

        if (norm >  1.0f) norm =  1.0f;
        if (norm < -1.0f) norm = -1.0f;

        ibus_state.ch[i] = norm;
    }

    ibus_state.valid = true;
    ibus_state.last_update_ms = HAL_GetTick();
}

// Periodic task: maps RC → commands + fail-safe
void ibus_task_update(void)
{
    uint32_t now = HAL_GetTick();
    static bool last_arm = false;

    // --- Timeout handling ---
    if (ibus_state.valid && (now - ibus_state.last_update_ms > IBUS_TIMEOUT_MS)) {
        ibus_state.valid = false;    // mark invalid
        LOGW("RC: link lost -> releasing RC control");
        // do NOT disarm automatically, let USB/ROS control continue
        return;
    }

    // --- If link is invalid, skip control ---
    if (!ibus_state.valid) {
        return;  // <== leaves target_rpm[] untouched so USB/ROS can command freely
    }

    // --- Normal RC mixing when valid ---
    const config_t* cfg = config_get();

    float throttle = ibus_state.ch[cfg->rc_ch_throttle];
    float steering = ibus_state.ch[cfg->rc_ch_steering];
    float arm_sw   = ibus_state.ch[cfg->rc_ch_arm];

    bool arm_now = (arm_sw > 0.5f);

    if (arm_now != last_arm) {
        if (arm_now) lyra_cmd_arm();
        else         lyra_cmd_disarm();
        last_arm = arm_now;
    }

    // only apply RC control when armed AND RC link valid
    if (arm_now && system_armed) {
        if (fabsf(throttle) < 0.05f) throttle = 0.0f;
        if (fabsf(steering) < 0.05f) steering = 0.0f;

        float v = throttle * 1.0f;
        float w = steering * 3.0f;

        if (v < 0.0f) {
            w = -w;
        }

        lyra_cmd_set_skid(v, w);
    }
}

bool rc_is_transmitter_active(void)
{
    const config_t* cfg = config_get();

    // Use raw values from ibus_state
    uint16_t throttle = ibus_state.raw[cfg->rc_ch_throttle];
    uint16_t steering = ibus_state.raw[cfg->rc_ch_steering];

    // FlySky typical failsafe: throttle=1000, steering=1500
    // If both at these values = likely failsafe active
    if (throttle < 1050 && steering > 1450 && steering < 1550) {
        return false;  // Transmitter likely off (failsafe active)
    }

    return true;  // Transmitter active
}
