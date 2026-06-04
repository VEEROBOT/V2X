// lyra_cmd.h
#ifndef LYRA_CMD_H
#define LYRA_CMD_H

#include <stdint.h>
#include <stdbool.h>

typedef enum {
    LYRA_OK = 0,
    LYRA_ERR_INVALID_ARG = 1,
    LYRA_ERR_DENIED      = 2  // e.g., trying to move while DISARMED
} LyraStatus_t;

LyraStatus_t lyra_cmd_arm(void);
LyraStatus_t lyra_cmd_disarm(void);
LyraStatus_t lyra_cmd_stop(void);
LyraStatus_t lyra_cmd_set_all_rpm(float rpm);
LyraStatus_t lyra_cmd_set_skid(float v_mps, float w_rad_s);
LyraStatus_t lyra_cmd_set_wheel_vel_rad_s(const float w_rad_s[4]);
LyraStatus_t lyra_cmd_set_pid(uint8_t idx, float kp, float ki, float kd);
LyraStatus_t lyra_cmd_set_ros_mode(uint8_t enable);
// later: lyra_cmd_set_config(), lyra_cmd_get_status(), etc.

#endif

