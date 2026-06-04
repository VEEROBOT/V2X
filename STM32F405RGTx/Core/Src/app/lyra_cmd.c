#include "app/lyra_cmd.h"
#include "app/app_main.h"
#include "config/robot_config.h"
#include "app/debug_log.h"
#include "app/config_storage.h"
#include "drivers/pid_controller.h"

#include <stdio.h>
#include <math.h>

// Globals from app_main.c
extern volatile uint8_t  system_armed;
extern volatile uint32_t last_cmd_ms;
extern volatile uint8_t  ros_mode_enabled;

extern config_t g_config;
extern PID_Controller_t pid_motor[5];

// ARM: allow motion, but no timeout until first motion command
LyraStatus_t lyra_cmd_arm(void)
{
    // Already armed → nothing to do, no spam
    if (system_armed) {
        return LYRA_OK;
    }

    system_armed = 1;
    robot_stop();          // clear any stale RPM
    last_cmd_ms = 0;       // timeout starts only after motion command

    LOGI("CMD: ARM -> system ARMED, all RPM = 0");
    return LYRA_OK;
}

// DISARM: immediate hard stop
LyraStatus_t lyra_cmd_disarm(void)
{
    // Already disarmed → nothing to do, no spam
    if (!system_armed) {
        return LYRA_OK;
    }

    system_armed = 0;
    robot_stop();
    last_cmd_ms = 0;

    LOGI("CMD: DISARM -> system DISARMED, all RPM = 0");
    return LYRA_OK;
}

// STOP: stop but keep system ARMED and watchdog alive
LyraStatus_t lyra_cmd_stop(void)
{
    robot_stop();
    last_cmd_ms = HAL_GetTick();   // treat STOP as a valid heartbeat
    LOGI("CMD: STOP -> all RPM = 0");
    return LYRA_OK;
}

// ALL <rpm>: set all wheels to same RPM (only when ARMED)
LyraStatus_t lyra_cmd_set_all_rpm(float rpm)
{
    if (!system_armed) {
    	LOGE("ERR: ALL ignored, system DISARMED (send ARM first)");
        return LYRA_ERR_DENIED;
    }

    app_set_all_rpm(rpm);
    last_cmd_ms = HAL_GetTick();

    char ack[64];
    snprintf(ack, sizeof(ack), "CMD: ALL %.1f RPM\r\n", rpm);
    LOGI("%s", ack);

    return LYRA_OK;
}

// SKID v w: skid-steer velocity command (only when ARMED)
LyraStatus_t lyra_cmd_set_skid(float v_mps, float w_rad_s)
{
    if (!system_armed) {
    	LOGE("ERR: SKID ignored, system DISARMED (send ARM first)");
        return LYRA_ERR_DENIED;
    }

    robot_cmd_skid(v_mps, w_rad_s);
    last_cmd_ms = HAL_GetTick();

    return LYRA_OK;
}

// Convert rad/s -> RPM
static float lyra_rad_s_to_rpm(float w_rad_s)
{
    // w [rad/s] * 60 / (2π)
    return (w_rad_s * 60.0f) / (2.0f * (float)M_PI);
}

// SET_WHEEL_VEL: 4x wheel angular velocities in rad/s (ROS style)
// Order: M1, M2, M3, M4
LyraStatus_t lyra_cmd_set_wheel_vel_rad_s(const float w_rad_s[4])
{
    if (!system_armed) {
    	LOGE("ERR: SET_WHEEL_VEL ignored, system DISARMED (send ARM first)");
        return LYRA_ERR_DENIED;
    }

    // Clamp against configured max_rad_s first
    float w_clamped[4];
    for (int i = 0; i < 4; i++) {
        float w = w_rad_s[i];

        if (w >  g_config.max_rad_s) w =  g_config.max_rad_s;
        if (w < -g_config.max_rad_s) w = -g_config.max_rad_s;

        w_clamped[i] = w;
    }

    // Convert to RPM and apply
    float rpm[4];
    for (int i = 0; i < 4; i++) {
        rpm[i] = lyra_rad_s_to_rpm(w_clamped[i]);

        // Hard clamp against motor physical max
        if (rpm[i] >  MOTOR_MAX_RPM) rpm[i] =  MOTOR_MAX_RPM;
        if (rpm[i] < -MOTOR_MAX_RPM) rpm[i] = -MOTOR_MAX_RPM;
    }

    app_set_motor_rpm(MOTOR_1, rpm[0]);
    app_set_motor_rpm(MOTOR_2, rpm[1]);
    app_set_motor_rpm(MOTOR_3, rpm[2]);
    app_set_motor_rpm(MOTOR_4, rpm[3]);

    last_cmd_ms = HAL_GetTick();

    static uint32_t vel_cmd_count = 0;
    vel_cmd_count++;

    if ((vel_cmd_count % 50) == 0) {
        char ack[96];
        snprintf(ack, sizeof(ack),
                 "CMD: SET_WHEEL_VEL [%.3f %.3f %.3f %.3f] rad/s -> [%.1f %.1f %.1f %.1f] RPM\r\n",
                 w_clamped[0], w_clamped[1], w_clamped[2], w_clamped[3],
                 rpm[0], rpm[1], rpm[2], rpm[3]);
        LOGI("%s", ack);
    }

    return LYRA_OK;
}

LyraStatus_t lyra_cmd_set_pid(uint8_t idx, float kp, float ki, float kd)
{
    if (idx < 1 || idx > 4) {
    	LOGE("CMD: SET_PID invalid motor index %u", idx);
        return LYRA_ERR_INVALID_ARG;
    }

    g_config.kp[idx-1] = kp;
    g_config.ki[idx-1] = ki;
    g_config.kd[idx-1] = kd;

    PID_Init(&pid_motor[idx],
             kp, ki, kd, PID_OUTPUT_LIMIT);

    LOGI("CMD: SET_PID M%u -> Kp=%.3f Ki=%.3f Kd=%.3f", idx, kp, ki, kd);

    return LYRA_OK;
}

LyraStatus_t lyra_cmd_set_ros_mode(uint8_t enable)
{
    ros_mode_enabled = enable ? 1 : 0;

    if (ros_mode_enabled) {
        g_transport_target = TRANSPORT_UART3;  // ROS2 on UART3
    } else {
        g_transport_target = TRANSPORT_USB;    // Debug on USB
    }

    LOGI("CMD: ROS_MODE %s (Transport: %s)",
         enable ? "ENABLED" : "DISABLED",
         (g_transport_target == TRANSPORT_UART3) ? "UART3" : "USB");

    return LYRA_OK;
}

// Set wheel angular velocities in rad/s (binary protocol)
LyraStatus_t lyra_cmd_set_wheel_vel(const float w_rad_s[4])
{
    if (!system_armed) {
    	LOGE("ERR: WHEEL_VEL ignored, system DISARMED (send ARM first)");
        return LYRA_ERR_DENIED;
    }

    // Convert rad/s → RPM and clamp
    float rpm[4];
    for (int i = 0; i < 4; i++) {
        rpm[i] = (w_rad_s[i] * 60.0f) / (2.0f * M_PI);
        if (rpm[i] >  MOTOR_MAX_RPM) rpm[i] =  MOTOR_MAX_RPM;
        if (rpm[i] < -MOTOR_MAX_RPM) rpm[i] = -MOTOR_MAX_RPM;
    }

    // Apply into controller
    app_set_motor_rpm(MOTOR_1, rpm[0]);
    app_set_motor_rpm(MOTOR_2, rpm[1]);
    app_set_motor_rpm(MOTOR_3, rpm[2]);
    app_set_motor_rpm(MOTOR_4, rpm[3]);

    last_cmd_ms = HAL_GetTick();

    LOGI("CMD: WHEEL_VEL -> [%.2f %.2f %.2f %.2f] rad/s",
         w_rad_s[0], w_rad_s[1], w_rad_s[2], w_rad_s[3]);

    return LYRA_OK;
}
