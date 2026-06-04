#ifndef APP_MAIN_H
#define APP_MAIN_H

#include "drivers/imu_lsm6dsrtr.h"
#include "drivers/pid_controller.h"
#include "config/robot_config.h"   // for MotorID_t, kinematics

#define RPM_AVG_WINDOW 20

void app_init(void);
void app_set_all_rpm(float rpm);
void app_set_motor_rpm(MotorID_t motor, float rpm);

// 🔹 New high-level robot APIs
void robot_cmd_skid(float v_mps, float w_rad_s);
void robot_stop(void);

// shared globals used by FreeRTOS tasks
extern PID_Controller_t pid_motor[5];
extern volatile float            target_rpm[5];
extern volatile float 			applied_rpm[5];
extern imu_sample_t     current_imu_data;

extern float    rpm_history[5][RPM_AVG_WINDOW];
extern uint8_t  rpm_index[5];
extern float    rpm_avg[5];

extern uint8_t  stall_cnt[5];
extern uint8_t  stall_latched[5];

// (you can keep control_mode/system_armed/last_cmd_ms externs in robot_config.h for later)

#endif
