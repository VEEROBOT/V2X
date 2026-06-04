#include "app/app_main.h"
#include "app/config_storage.h"
#include "config/robot_config.h"
#include "app/debug_log.h"
#include "drivers/motor_driver.h"
#include "drivers/imu_lsm6dsrtr.h"
#include "drivers/encoder_driver.h"
#include "drivers/pid_controller.h"
#include "usbd_cdc_if.h"
#include "rc/rc_ibus.h"
#include <stdio.h>
#include <math.h>
#include <string.h>
#include "app/lyra_proto.h"
#include "app/oled_display.h"

PID_Controller_t pid_motor[5];
volatile float            target_rpm[5] = {0};
volatile float 	 		 applied_rpm[5] = {0};
imu_sample_t     current_imu_data = {0};

float    rpm_history[5][RPM_AVG_WINDOW];
uint8_t  rpm_index[5] = {0};
float    rpm_avg[5] = {0};

// Stall protection - use constants from robot_config.h
uint8_t stall_cnt[5] = {0};
uint8_t stall_latched[5] = {0};

volatile uint8_t control_mode = CONTROL_MODE_PID;
volatile uint8_t  system_armed = 0;   // 0 = DISARMED, 1 = ARMED
volatile uint32_t last_cmd_ms  = 0;   // last time a velocity command was received
volatile uint32_t last_control_loop_ms = 0;

LyraProtoParser_t g_lyra_parser;

volatile uint8_t ros_mode_enabled = 0; // 0 = normal, 1 = ROS mode (no ASCII telemetry)

TransportTarget_t g_transport_target = TRANSPORT_UART3;  // Default to USB

static float clamp_value(float x, float lo, float hi)
{
    if (x < lo) return lo;
    if (x > hi) return hi;
    return x;
}

// Set individual motor RPM
void app_set_motor_rpm(MotorID_t motor, float rpm)
{
    if (motor >= MOTOR_1 && motor <= MOTOR_4) {
        target_rpm[motor] = clamp_value(rpm, -MOTOR_MAX_RPM, MOTOR_MAX_RPM);
    }
}

// simple helper to set all motors to same RPM (for testing)
void app_set_all_rpm(float rpm)
{
    for (int m = MOTOR_1; m <= MOTOR_4; m++) {
        target_rpm[m] = clamp_value(rpm, -MOTOR_MAX_RPM, MOTOR_MAX_RPM);
    }
}

// Convert wheel linear speed (m/s) -> wheel RPM
static float mps_to_rpm(float v_mps)
{
    // Each wheel revolution travels WHEEL_CIRCUMFERENCE meters
    float rev_per_s = v_mps / WHEEL_CIRCUMFERENCE;
    float rpm       = rev_per_s * 60.0f;

    // Clamp to motor’s rated max
    if (rpm >  MOTOR_MAX_RPM)  rpm =  MOTOR_MAX_RPM;
    if (rpm < -MOTOR_MAX_RPM)  rpm = -MOTOR_MAX_RPM;
    return rpm;
}

// High-level skid-steer command
// v_mps  : linear velocity (+ forward, - backward)
// w_rad_s: angular velocity (+ CCW turn)
void robot_cmd_skid(float v_mps, float w_rad_s)
{
    if (v_mps < 0.0f) {
        w_rad_s = -w_rad_s;
    }
    // Track width between left & right wheel centers
    float half_track = WHEEL_BASE_M * 0.5f;

    // Standard differential-drive kinematics:
    // left  = v - ω * L/2
    // right = v + ω * L/2
    float v_left_mps  = v_mps - (w_rad_s * half_track);
    float v_right_mps = v_mps + (w_rad_s * half_track);

    float rpm_left  = mps_to_rpm(v_left_mps);
    float rpm_right = mps_to_rpm(v_right_mps);

    // For a skid-steer 4WD:
    //   M1, M2 = left side
    //   M3, M4 = right side
    // Motor direction mapping is handled inside Motor_SetSpeed()
    app_set_motor_rpm(MOTOR_1, rpm_left);
    app_set_motor_rpm(MOTOR_2, rpm_left);
    app_set_motor_rpm(MOTOR_3, rpm_right);
    app_set_motor_rpm(MOTOR_4, rpm_right);
}

// Convenience stop
void robot_stop(void)
{
    app_set_all_rpm(0.0f);
    for (int m = MOTOR_1; m <= MOTOR_4; m++) {
        applied_rpm[m] = 0.0f;
    }
}

void app_init(void)
{
    // Optional: wait up to 3 seconds for USB CDC enumeration
    uint32_t t0 = HAL_GetTick();
    while (!USB_CDC_IsReady() && (HAL_GetTick() - t0) < 3000) {
        HAL_Delay(10);
    }

    HAL_Delay(200);

	#if BOARD_HAS_LED_PA10
		__HAL_RCC_GPIOA_CLK_ENABLE();
		GPIO_InitTypeDef cfg = {0};
		cfg.Pin = LED_PIN;
		cfg.Mode = GPIO_MODE_OUTPUT_PP;
		cfg.Pull = GPIO_NOPULL;
		cfg.Speed = GPIO_SPEED_FREQ_LOW;
		HAL_GPIO_Init(LED_PORT, &cfg);
		HAL_GPIO_WritePin(LED_PORT, LED_PIN, GPIO_PIN_SET);
		HAL_Delay(25);
		HAL_GPIO_WritePin(LED_PORT, LED_PIN, GPIO_PIN_RESET);
	#endif

    // 1) Load configuration (flash or defaults)
    config_init();

    // Set transport from config
    g_transport_target = (TransportTarget_t)g_config.default_transport;

    LOGI("=== Lyra Controller Init ===");
        HAL_Delay(200);

    config_print();   // optional noise; useful while bringup

    lyra_proto_parser_init(&g_lyra_parser);

    // 2) Initialize peripherals that do NOT depend on config
    imu_init();            // IMU
    Motor_Init();          // PWM + DRV8874
    Encoder_Init();        // timers in encoder mode
    Encoder_ResetAll();    // zero tick counters
    ibus_init();           // RC input


    // 3) Initialize PID controllers using config gains
    for (int i = MOTOR_1; i <= MOTOR_4; i++) {
        PID_Init(&pid_motor[i],
                 g_config.kp[i - 1],
                 g_config.ki[i - 1],
                 g_config.kd[i - 1],
                 PID_OUTPUT_LIMIT);
    }

    control_mode = CONTROL_MODE_PID;

    // 4) Safe start: all RPM zero, DISARMED
    robot_stop();
    system_armed = 0;
    last_cmd_ms  = 0;

    oled_app_init();

    LOGI("OK - System Initialized, motors stopped, STATE=DISARMED");
}

