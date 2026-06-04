#ifndef PID_CONTROLLER_H
#define PID_CONTROLLER_H

#include <stdint.h>

typedef struct {
    // Tuning parameters
    float kp;
    float ki;
    float kd;

    // State variables
    float integral;
    float prev_measurement;
    float prev_output;

    // Limits
    float output_limit;        // Max output (e.g., 100 for motor speed)
    float integral_limit;      // Anti-windup limit

    // Filtering & stability
    float output_filter;       // Low-pass filter coefficient (0.0-1.0)
    float deadband;           // Ignore errors smaller than this
    float max_output_change;  // Rate limit (max change per cycle)

    // Timing
    uint32_t last_time_ms;
} PID_Controller_t;

// Initialize PID controller with safe defaults
void PID_Init(PID_Controller_t *pid, float kp, float ki, float kd, float output_limit);

// Compute PID output (call every control cycle)
float PID_Compute(PID_Controller_t *pid, float setpoint, float measurement);

// Reset integral and error terms
void PID_Reset(PID_Controller_t *pid);

// Update tuning parameters at runtime
void PID_SetTunings(PID_Controller_t *pid, float kp, float ki, float kd);

// Enable/disable output filtering
void PID_SetOutputFilter(PID_Controller_t *pid, float filter_coef);

// Set deadband (error threshold)
void PID_SetDeadband(PID_Controller_t *pid, float deadband);

// Dynamically adjust PID gains based on speed (RPM)
void PID_SetDynamicTunings(PID_Controller_t *pid, float speed_rpm);

#endif
