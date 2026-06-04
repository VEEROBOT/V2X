#include "drivers/pid_controller.h"
#include "config/robot_config.h"
#include "app/debug_log.h"
#include "main.h"
#include <math.h>
#include <string.h>
#include <stdbool.h>

void PID_Init(PID_Controller_t *pid, float kp, float ki, float kd, float output_limit)
{
    memset(pid, 0, sizeof(PID_Controller_t));

    pid->kp = kp;
    pid->ki = ki;
    pid->kd = kd;

    pid->output_limit = output_limit;
    pid->integral_limit = output_limit * PID_INTEGRAL_LIMIT;

    // Safe defaults for stability
    pid->output_filter = PID_OUTPUT_FILTER;
    pid->deadband = PID_DEADBAND_RPM;
    pid->max_output_change = PID_MAX_OUTPUT_CHANGE;

    pid->last_time_ms = HAL_GetTick();
}

float PID_Compute(PID_Controller_t *pid, float setpoint, float measurement)
{
    // --- Time step ---
    uint32_t now = HAL_GetTick();
    float dt = (now - pid->last_time_ms) / 1000.0f;
    pid->last_time_ms = now;

    // Sanity check on dt (allow 20-200ms)
    if (dt <= 0.02f || dt > 0.2f) {
        return pid->prev_output;
    }

    // --- Error calculation with deadband ---
    float error = setpoint - measurement;
    if (fabsf(error) < pid->deadband) {
        error = 0.0f;
    }

    // --- Proportional term ---
    float p_term = pid->kp * error;

    // --- Integral term with simple clamping anti-windup ---
    // Only integrate if we're not saturated OR error would reduce saturation
    float pre_sat_output = p_term + pid->ki * pid->integral;
    bool saturated_positive = (pre_sat_output >= pid->output_limit);
    bool saturated_negative = (pre_sat_output <= -pid->output_limit);

    // Conditional integration: don't integrate if pushing further into saturation
    if (!(saturated_positive && error > 0.0f) &&
        !(saturated_negative && error < 0.0f)) {
        pid->integral += error * dt;

        // Clamp integral to limits
        if (pid->integral > pid->integral_limit) {
            pid->integral = pid->integral_limit;
        } else if (pid->integral < -pid->integral_limit) {
            pid->integral = -pid->integral_limit;
        }
    }

    float i_term = pid->ki * pid->integral;

    // --- Derivative term on MEASUREMENT (reduces noise) ---
    float d_meas = (measurement - pid->prev_measurement) / dt;
    float d_term = -pid->kd * d_meas;  // Negative because derivative-on-measurement
    pid->prev_measurement = measurement;

    // --- Compute raw output ---
    float output = p_term + i_term + d_term;

    // --- Output saturation ---
    if (output > pid->output_limit) {
        output = pid->output_limit;
    } else if (output < -pid->output_limit) {
        output = -pid->output_limit;
    }

    // --- Rate limiting (prevent sudden jumps) ---
    float delta = output - pid->prev_output;
    if (delta > pid->max_output_change) {
        output = pid->prev_output + pid->max_output_change;
    } else if (delta < -pid->max_output_change) {
        output = pid->prev_output - pid->max_output_change;
    }

    // --- Low-pass filter on output (smooth response) ---
    output = pid->output_filter * pid->prev_output + (1.0f - pid->output_filter) * output;

    pid->prev_output = output;
    return output;
}

void PID_Reset(PID_Controller_t *pid)
{
    pid->integral = 0.0f;
    pid->prev_measurement = 0.0f;
    pid->prev_output = 0.0f;
    pid->last_time_ms = HAL_GetTick();
}

void PID_SetTunings(PID_Controller_t *pid, float kp, float ki, float kd)
{
    pid->kp = kp;
    pid->ki = ki;
    pid->kd = kd;
}

void PID_SetOutputFilter(PID_Controller_t *pid, float filter_coef)
{
    if (filter_coef >= 0.0f && filter_coef <= 1.0f) {
        pid->output_filter = filter_coef;
    }
}

void PID_SetDeadband(PID_Controller_t *pid, float deadband)
{
    pid->deadband = deadband;
}

void PID_SetDynamicTunings(PID_Controller_t *pid, float speed_rpm)
{
    float abs_rpm = fabsf(speed_rpm);

    // ===== 1. LINEAR GAIN SCALING (0 to MAX RPM) =====
    float gain_scale = abs_rpm / MOTOR_MAX_RPM;
    if (gain_scale > 1.0f) gain_scale = 1.0f;

    // Gains scale linearly from low to high speed values
    float kp = PID_KP_LOW_SPEED +
               gain_scale * (PID_KP_HIGH_SPEED - PID_KP_LOW_SPEED);
    float ki = PID_KI_LOW_SPEED +
               gain_scale * (PID_KI_HIGH_SPEED - PID_KI_LOW_SPEED);
    float kd = PID_KD_LOW_SPEED +
               gain_scale * (PID_KD_HIGH_SPEED - PID_KD_LOW_SPEED);

    PID_SetTunings(pid, kp, ki, kd);

    // ===== 2. LINEAR DEADBAND SCALING =====
    float deadband_scale = abs_rpm / PID_DEADBAND_SCALE_RPM;
    if (deadband_scale > 1.0f) deadband_scale = 1.0f;
    pid->deadband = PID_DEADBAND_MIN +
                   deadband_scale * (PID_DEADBAND_MAX - PID_DEADBAND_MIN);

    // ===== 3. LINEAR OUTPUT CHANGE LIMIT (optional) =====
    // You could also scale max_output_change if needed
    // pid->max_output_change = MIN_OUTPUT_CHANGE +
    //                         scale * (MAX_OUTPUT_CHANGE - MIN_OUTPUT_CHANGE);
}
