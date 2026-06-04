#ifndef ENCODER_DRIVER_H
#define ENCODER_DRIVER_H

#include "stm32f4xx_hal.h"
#include "config/robot_config.h"
#include "app/debug_log.h"

#ifdef __cplusplus
extern "C" {
#endif

/* ===========================================================
 * 🧮 ENCODER DATA STRUCTURES
 * =========================================================== */

typedef struct {
    int32_t last_raw_count;
    int64_t total_ticks;
    float vel_ticks_per_s;
    float vel_rps;
    float vel_rpm;
    float vel_mps;
} EncoderState_t;

/* ===========================================================
 * 🔧 INITIALIZATION & UPDATE FUNCTIONS
 * =========================================================== */

void Encoder_Init(void);
void Encoder_Update(void);
void Encoder_UpdateWithDt(float dt_s);

/* ===========================================================
 * 📈 VELOCITY & POSITION GETTERS
 * =========================================================== */

int64_t Encoder_GetTotalTicks(MotorID_t m);
float Encoder_GetTicksPerSecond(MotorID_t m);
float Encoder_GetRPS(MotorID_t m);
float Encoder_GetRPM(MotorID_t m);
float Encoder_GetMPS(MotorID_t m);

/* ===========================================================
 * 🛠️ UTILITY & CONFIGURATION FUNCTIONS
 * =========================================================== */

void Encoder_Reset(MotorID_t m);
void Encoder_ResetAll(void);
void Encoder_SetPolarity(MotorID_t m, int8_t polarity);
uint32_t Encoder_GetRawCount(MotorID_t m);

#ifdef __cplusplus
}
#endif

#endif /* ENCODER_DRIVER_H */
