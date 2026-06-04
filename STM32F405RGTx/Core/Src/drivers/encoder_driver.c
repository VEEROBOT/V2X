#include "drivers/encoder_driver.h"
#include <string.h>
#include <stdio.h>

/* ===== External timer handles ===== */
extern TIM_HandleTypeDef htim1;
extern TIM_HandleTypeDef htim2;
extern TIM_HandleTypeDef htim4;
extern TIM_HandleTypeDef htim8;

/* ===== Encoder configuration with mapping ===== */
static TIM_HandleTypeDef* const s_physical_enc_timer[1 + ENCODER_COUNT] = {
    NULL, ENC1_TIMER, ENC2_TIMER, ENC3_TIMER, ENC4_TIMER
};

/* ===== Encoder mapping (same as motor mapping) ===== */
static const uint8_t s_encoder_map[5] = ENCODER_MAP;

/* Helper: get physical encoder from logical motor ID */
static inline TIM_HandleTypeDef* get_physical_encoder(MotorID_t logical_motor) {
    if (logical_motor < 1 || logical_motor > 4) return NULL;
    uint8_t physical_idx = s_encoder_map[logical_motor];
    return s_physical_enc_timer[physical_idx];
}

/* Per-motor state */
static EncoderState_t s_state[1 + ENCODER_COUNT];
static int8_t s_polarity[1 + ENCODER_COUNT] = ENCODER_POLARITY_MAP;

/* Simple state tracking */
static uint32_t s_last_count[1 + ENCODER_COUNT] = {0};

/* Helper: read current CNT - ALL treated as 16-bit for consistency */
static inline uint32_t enc_read_cnt(MotorID_t logical_motor) {
    TIM_HandleTypeDef* t = get_physical_encoder(logical_motor);
    if (!t || !t->Instance) return 0u;

    // Read and mask to 16-bit for ALL timers (intentional for consistency)
    return t->Instance->CNT & 0xFFFF;
}

void Encoder_Init(void) {
    memset(s_state, 0, sizeof(s_state));
    memset(s_last_count, 0, sizeof(s_last_count));

    for (int logical_motor = MOTOR_1; logical_motor <= MOTOR_4; ++logical_motor) {
        TIM_HandleTypeDef* t = get_physical_encoder((MotorID_t)logical_motor);
        if (!t || !t->Instance) continue;

        // Reset counter and start encoder interface
        __HAL_TIM_SET_COUNTER(t, 0);
        HAL_TIM_Encoder_Start(t, TIM_CHANNEL_ALL);

        // Disable update interrupts - use polling only
        __HAL_TIM_DISABLE_IT(t, TIM_IT_UPDATE);

        s_last_count[logical_motor] = enc_read_cnt((MotorID_t)logical_motor);
        s_state[logical_motor].last_raw_count = (int32_t)s_last_count[logical_motor];
        s_state[logical_motor].total_ticks = 0;
    }
}

void Encoder_Update(void)
{
    const float dt_s = (float)PID_SAMPLE_TIME_MS / 1000.0f;

    // ✅ REMOVED REDUNDANT LOW-PASS FILTER
    // Only use moving average in app_rtos.c OR low-pass here, not both
    // For now, keeping it DISABLED for fastest response

    for (int logical_motor = MOTOR_1; logical_motor <= MOTOR_4; ++logical_motor)
    {
        TIM_HandleTypeDef* t = get_physical_encoder((MotorID_t)logical_motor);
        if (!t || !t->Instance) continue;

        uint32_t curr_count = enc_read_cnt((MotorID_t)logical_motor);
        uint32_t prev_count = s_last_count[logical_motor];

        // Compute 16-bit delta for all timers (intentional wrapping)
        int32_t delta = (int16_t)(curr_count - prev_count);

        // Apply polarity
        delta *= s_polarity[logical_motor];

        // Update state
        s_last_count[logical_motor] = curr_count;
        s_state[logical_motor].last_raw_count = (int32_t)curr_count;
        s_state[logical_motor].total_ticks += delta;

        // Compute velocities WITHOUT additional filtering
        if (dt_s > 0)
        {
            float ticks_per_s = (float)delta / dt_s;
            float vel_rps = ticks_per_s / (float)ENCODER_TICKS_REV;
            float vel_rpm = vel_rps * 60.0f;
            float vel_mps = vel_rps * (float)WHEEL_CIRCUMFERENCE;

            // Store RAW results (filtering done in app_rtos.c if needed)
            s_state[logical_motor].vel_ticks_per_s = ticks_per_s;
            s_state[logical_motor].vel_rps = vel_rps;
            s_state[logical_motor].vel_rpm = vel_rpm;
            s_state[logical_motor].vel_mps = vel_mps;
        }
    }
}

/* ===== Public API ===== */
int64_t Encoder_GetTotalTicks(MotorID_t m) {
    if (m < MOTOR_1 || m > MOTOR_4) return 0;
    return s_state[m].total_ticks;
}

float Encoder_GetTicksPerSecond(MotorID_t m) {
    if (m < MOTOR_1 || m > MOTOR_4) return 0.0f;
    return s_state[m].vel_ticks_per_s;
}

float Encoder_GetRPS(MotorID_t m) {
    if (m < MOTOR_1 || m > MOTOR_4) return 0.0f;
    return s_state[m].vel_rps;
}

float Encoder_GetRPM(MotorID_t m) {
    if (m < MOTOR_1 || m > MOTOR_4) return 0.0f;
    return s_state[m].vel_rpm;
}

float Encoder_GetMPS(MotorID_t m) {
    if (m < MOTOR_1 || m > MOTOR_4) return 0.0f;
    return s_state[m].vel_mps;
}

uint32_t Encoder_GetRawCount(MotorID_t m) {
    if (m < MOTOR_1 || m > MOTOR_4) return 0;
    return enc_read_cnt(m);
}

void Encoder_Reset(MotorID_t m) {
    if (m < MOTOR_1 || m > MOTOR_4) return;
    TIM_HandleTypeDef* t = get_physical_encoder(m);
    if (t && t->Instance) {
        __HAL_TIM_SET_COUNTER(t, 0);
    }
    s_last_count[m] = 0;
    s_state[m].last_raw_count = 0;
    s_state[m].total_ticks = 0;
    s_state[m].vel_ticks_per_s = 0.0f;
    s_state[m].vel_rps = 0.0f;
    s_state[m].vel_rpm = 0.0f;
    s_state[m].vel_mps = 0.0f;
}

void Encoder_ResetAll(void) {
    for (int m = MOTOR_1; m <= MOTOR_4; ++m) {
        Encoder_Reset((MotorID_t)m);
    }
}

void Encoder_SetPolarity(MotorID_t m, int8_t polarity) {
    if (m < MOTOR_1 || m > MOTOR_4) return;
    s_polarity[m] = (polarity >= 0) ? +1 : -1;
}

void Encoder_UpdateWithDt(float dt_s) {
    for (int logical_motor = MOTOR_1; logical_motor <= MOTOR_4; ++logical_motor) {
        TIM_HandleTypeDef* t = get_physical_encoder((MotorID_t)logical_motor);
        if (!t || !t->Instance) continue;

        uint32_t curr_count = enc_read_cnt((MotorID_t)logical_motor);
        uint32_t prev_count = s_last_count[logical_motor];

        int32_t delta = (int16_t)(curr_count - prev_count);
        delta *= s_polarity[logical_motor];

        s_last_count[logical_motor] = curr_count;
        s_state[logical_motor].last_raw_count = (int32_t)curr_count;
        s_state[logical_motor].total_ticks += delta;

        // Use the provided dt_s
        if (dt_s > 0) {
            float ticks_per_s = (float)delta / dt_s;
            s_state[logical_motor].vel_ticks_per_s = ticks_per_s;
            s_state[logical_motor].vel_rps = ticks_per_s / (float)ENCODER_TICKS_REV;
            s_state[logical_motor].vel_rpm = s_state[logical_motor].vel_rps * 60.0f;
            s_state[logical_motor].vel_mps = s_state[logical_motor].vel_rps * (float)WHEEL_CIRCUMFERENCE;
        }
    }
}
