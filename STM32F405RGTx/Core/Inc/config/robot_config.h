#ifndef ROBOT_CONFIG_H
#define ROBOT_CONFIG_H

#include "main.h"
#include <string.h>
#include <stdio.h>
#include "usbd_cdc_if.h"

/* ===========================================================
 *  🤖 STM32 Lyra Robot - Hardware Configuration
 *  Board: STM32F405RGT6 + DRV8874 + LSM6DSRTR
 *  Version: 1.1 (Nov 2025)
 * =========================================================== */

// -------------------------------------------------------------
// 🧠 SYSTEM INFO
// -------------------------------------------------------------
#define ROBOT_NAME          "Lyra Robotics Controller"
#define MCU_MODEL           "STM32F405RGT6"
#define BOARD_VERSION       "v1.1"
#define FIRMWARE_VERSION    "2025.11.05"

// -------------------------------------------------------------
// ⚙️ SYSTEM CLOCK & PWM CONFIGURATION
// -------------------------------------------------------------
#define SYS_CORE_CLOCK_HZ   168000000U
#define PWM_FREQUENCY_HZ    20000
#define PWM_MAX             4199        // ARR value in CubeMX
#define MOTOR_SPEED_RANGE   100         // Logical range -100..+100

// -------------------------------------------------------------
// ⚡ MOTOR DRIVER CONFIGURATION (DRV8874)
// -------------------------------------------------------------
#define MOTOR_DRIVER_TYPE   "DRV8874"
#define MOTOR_COUNT         4

// ✅ Logical motor IDs (software-level consistency)
typedef enum {
    MOTOR_1 = 1,
    MOTOR_2,
    MOTOR_3,
    MOTOR_4
} MotorID_t;

// ===== TRANSPORT CONFIGURATION =====
typedef enum {
    TRANSPORT_USB = 0,      // Debug via USB CDC
    TRANSPORT_UART3 = 1,    // ROS2 via UART3
    TRANSPORT_BOTH = 2      // Mirror to both (future)
} TransportTarget_t;

extern TransportTarget_t g_transport_target;

// 🧩 Physical wiring → logical mapping
// This maps logical software order (M1..M4) → physical ports
// Example: Logical M2 is physically at M3’s port
// So you can swap hardware connections without rewriting code
// Index 0 is a dummy to make it 1-based.
#define MOTOR_MAP { 0, 1, 3, 2, 4 }
#define MOTOR_DIRECTION_MAP {0, -1, -1, +1, +1}
static const uint8_t physical_motor_map[5] = MOTOR_MAP;

// Implement a real “stop mode”
#define CONTROL_MODE_OFF  0
#define CONTROL_MODE_PID  1
#define CMD_TIMEOUT_MS   5000    // if no command for this ms -> auto-stop

extern volatile uint8_t control_mode;
extern volatile uint8_t system_armed;
extern volatile uint32_t last_cmd_ms;
extern volatile uint32_t last_control_loop_ms;
extern volatile uint8_t ros_mode_enabled;

// 💤 Shared sleep/enable
#define MOTOR_NSLEEP_PORT   GPIOB
#define MOTOR_NSLEEP_PIN    GPIO_PIN_3

// 🧭 PWM timers and channels
#define M1_PWM_TIMER        &htim3
#define M1_PWM_CH1          TIM_CHANNEL_3
#define M1_PWM_CH2          TIM_CHANNEL_4

#define M2_PWM_TIMER        &htim5
#define M2_PWM_CH1          TIM_CHANNEL_3
#define M2_PWM_CH2          TIM_CHANNEL_4

#define M3_PWM_TIMER        &htim3
#define M3_PWM_CH1          TIM_CHANNEL_1
#define M3_PWM_CH2          TIM_CHANNEL_2

#define M4_PWM_TIMER        &htim12
#define M4_PWM_CH1          TIM_CHANNEL_1
#define M4_PWM_CH2          TIM_CHANNEL_2

// 🛑 Fault pins (active-low)
#define M1_FAULT_PORT       GPIOB
#define M1_FAULT_PIN        GPIO_PIN_0
#define M2_FAULT_PORT       GPIOB
#define M2_FAULT_PIN        GPIO_PIN_1
#define M3_FAULT_PORT       GPIOC
#define M3_FAULT_PIN        GPIO_PIN_4
#define M4_FAULT_PORT       GPIOC
#define M4_FAULT_PIN        GPIO_PIN_5
#define FAULT_ACTIVE_LOW    1
#define FAULT_DEBOUNCE_MS   10

// Motor RPM Limits
#define MOTOR_MAX_RPM          150.0f   // Max motor's spec sheet limit (178)

// -------------------------------------------------------------
// ⚙️ ENCODER CONFIGURATION
// -------------------------------------------------------------
#define ENCODER_COUNT       4
#define ENC1_TIMER          &htim1
#define ENC2_TIMER          &htim2
#define ENC3_TIMER          &htim4
#define ENC4_TIMER          &htim8
#define ENC_RESOLUTION_CPR  900

// 🧩 Encoder mapping - same mapping as motors
// Logical encoder order → physical encoder timers
#define ENCODER_MAP { 0, 1, 3, 2, 4 }
#define ENCODER_POLARITY_MAP {0, +1, +1, -1, -1}

// -------------------------------------------------------------
// 🧭 IMU CONFIGURATION (LSM6DSRTR)
// -------------------------------------------------------------
#define IMU_I2C_BUS         &hi2c2
#define IMU_ADDR_7BIT       0x6A
#define IMU_WHOAMI_EXPECTED 0x6B
#define IMU_GYRO_FS_DPS     2000.0f
#define IMU_ACC_FS_G        2.0f
#define IMU_ODR_HZ          104.0f
#define IMU_INT_PORT        GPIOA
#define BOARD_HAS_LED_PA10  1
#define LED_PORT 			GPIOA
#define LED_PIN  			GPIO_PIN_10

// -------------------------------------------------------------
// 💡 RGB LED / Indicator
// -------------------------------------------------------------
#define RGB_PORT            GPIOA
#define RGB_PIN             GPIO_PIN_15
#define RGB_COUNT           1

// -------------------------------------------------------------
// 🔊 BUZZER / SPEAKER
// -------------------------------------------------------------
#define BUZZER_USE_DAC
#define BUZZER_DAC_CHANNEL  DAC_CHANNEL_1

// -------------------------------------------------------------
// ⚡ ADC INPUTS
// -------------------------------------------------------------
#define ADC_USE_DMA
#define ADC_BATT_VOLT_CH    ADC_CHANNEL_10
#define ADC_BATT_CURR_CH    ADC_CHANNEL_11
#define ADC_SENSOR1_CH      ADC_CHANNEL_12
#define ADC_SENSOR2_CH      ADC_CHANNEL_13

// -------------------------------------------------------------
// BATTERY MEASUREMENT CALIBRATION
// -------------------------------------------------------------
// Multiplier applied to computed battery voltage
// 1.0000 = no correction
// <1.0   = ADC reads high
// >1.0   = ADC reads low
#define BATTERY_CAL_FACTOR   0.989f

// -------------------------------------------------------------
// 🧩 COMMUNICATION
// -------------------------------------------------------------
#define UART_PRIMARY        &huart3
#define UART_DEBUG          &huart5
#define CAN1_ACTIVE
#define CAN2_ACTIVE
#define I2C_SENSOR_BUS      &hi2c2
#define SPI_MAIN_BUS        &hspi1
#define USB_DEVICE_ACTIVE   1

/* ------------------------------------------------------------
	Symptom	Problem	Solution	Parameter Change
	Never reaches 10 RPM (stuck at 8-9 RPM)	Insufficient power	Increase P gain	Kp: 8.0 → 10.0
	Overshoots then oscillates (11→9→11 RPM)	Too aggressive	Reduce P gain	Kp: 8.0 → 6.0
	Takes >2 seconds to reach 10 RPM	Too slow	Increase P, add I	Kp: 8.0 → 9.0, Ki: 0.6 → 0.8
	Steady-state error > 0.5 RPM	Need more integral	Increase I gain	Ki: 0.6 → 0.9
	Jerky, pulsing motion	Too much D or rate limit	Reduce D, increase rate limit	Kd: 0.008 → 0.004, MAX_CHANGE: 12 → 15
	Slow oscillations (1-2 second period)	Too much I	Reduce I gain	Ki: 0.6 → 0.4
	Motor stops/start repeatedly	Stall detection too sensitive	Increase stall threshold	STALL_THRESH: 2.0 → 3.0

*/

// 🧮 CONTROL / PID
// -------------------------------------------------------------
// Default PID gains
#define PID_KP_DEFAULT   		4.0f
#define PID_KI_DEFAULT   		1.0f
#define PID_KD_DEFAULT   		0.06f
#define PID_OUTPUT_LIMIT        MOTOR_SPEED_RANGE		// changed from 4199 to MOTOR_SPEED_RANGE
#define PID_SAMPLE_TIME_MS      50

// Low-speed tuning
#define PID_KP_LOW_SPEED        3.0f
#define PID_KI_LOW_SPEED        0.8f
#define PID_KD_LOW_SPEED        0.05f

// High-speed tuning
#define PID_KP_HIGH_SPEED       5.0f
#define PID_KI_HIGH_SPEED       1.2f
#define PID_KD_HIGH_SPEED       0.08f

// ===== STABILITY PARAMETERS =====
// THESE CONTROL JERKINESS
#define PID_DEADBAND_MIN          0.2f    // Deadband at 0 RPM
#define PID_DEADBAND_MAX          3.0f    // Deadband at max RPM (178 RPM)
#define PID_DEADBAND_SCALE_RPM    MOTOR_MAX_RPM  // RPM at which deadband reaches max

#define PID_OUTPUT_FILTER       0.8f
#define PID_DEADBAND_RPM        0.5f   // Default/minimum deadband
#define PID_INTEGRAL_LIMIT      0.5f   // 50% of output limit
#define PID_MAX_OUTPUT_CHANGE   15.0f  // Max 20% change per cycle

// Keep backward compatibility
#define PID_KP              PID_KP_DEFAULT
#define PID_KI              PID_KI_DEFAULT
#define PID_KD              PID_KD_DEFAULT

// Motor-specific feedforward gains (overcome friction differences)
#define FEEDFORWARD_MIN_RPM   5.0f    // Minimum RPM to apply feedforward
#define MOTOR_FF_GAIN_1       1.2f
#define MOTOR_FF_GAIN_2       1.2f
#define MOTOR_FF_GAIN_3       1.2f
#define MOTOR_FF_GAIN_4       1.2f

// Max RPM change allowed per control cycle (for setpoint ramping)
#define MAX_RPM_STEP_PER_CYCLE   5.0f   // tune this; higher = more aggressive

// -------------------------------------------------------------
// 🛡️ STALL DETECTION & RECOVERY
// -------------------------------------------------------------
#define STALL_DETECTION_RPM_THRESHOLD    1.0f   // RPM below which motor is stalled
#define STALL_DETECTION_CYCLES           12      // Cycles before latching stall
#define STALL_RECOVERY_CREEP_PWM         80      // PWM% for good restart
#define STALL_RECOVERY_RPM_THRESHOLD     3.0f   // RPM above which stall is cleared

// -------------------------------------------------------------
// 🧱 ROBOT KINEMATICS
// -------------------------------------------------------------
#define WHEEL_DIAMETER_M    0.13f
#define WHEEL_BASE_M        0.295f
#define ENCODER_TICKS_REV   (ENC_RESOLUTION_CPR * 4)
#define WHEEL_CIRCUMFERENCE (3.14159f * WHEEL_DIAMETER_M)
#define DISTANCE_PER_TICK   (WHEEL_CIRCUMFERENCE / ENCODER_TICKS_REV)
#define GEAR_RATIO          37.0f

// -------------------------------------------------------------
// 🧰 DEBUG SETTINGS
// -------------------------------------------------------------
#define DEBUG_USB_OUTPUT    1
#define ENCODER_DEBUG 1

#endif /* ROBOT_CONFIG_H */


/* ===========================================================
 *  ENCODER / GEARBOX / WHEEL RELATIONSHIP  (JGB37-3530)
 *  Mechanical chain:
 *      [Encoder] → [DC motor shaft] → [Gearbox ~37:1] → [Wheel shaft]
 *  Important points:
 *  -----------------
 *  1) The encoder is mounted on the **motor shaft**, not on the wheel.
 *  2) However, for this project we treat the system using an
 *     **effective counts-per-wheel-revolution** value:
 *        - One full wheel rotation ≈ 900 CPR (Counts Per Revolution)
 *        - Timer is in quadrature X4 mode → it sees 4 ticks per encoder cycle
 *        - So:
 *              ENCODER_TICKS_REV ≈ 900 * 4 = ~3600 ticks / wheel rev
 *     This matches measurement from manual testing:
 *        ~±3600 total ticks when the wheel is rotated once by hand.
 *  3) Because we work in **wheel units**, we do NOT explicitly use
 *     GEAR_RATIO in the encoder → velocity math. The gear ratio is
 *     already "baked into" ENCODER_TICKS_REV (since that value is
 *     defined per wheel revolution, not per motor shaft revolution).
 *  4) Units used in the encoder driver:
 *        - ENCODER_TICKS_REV : ticks per **wheel** revolution
 *        - Encoder_GetRPM()  : wheel RPM        (not motor RPM)
 *        - Encoder_GetRPS()  : wheel rev/s
 *        - Encoder_GetMPS()  : linear wheel speed in m/s
 *     With:
 *        WHEEL_CIRCUMFERENCE = π * WHEEL_DIAMETER_M
 *        DISTANCE_PER_TICK   = WHEEL_CIRCUMFERENCE / ENCODER_TICKS_REV
 *  5) MOTOR_MAX_RPM is defined as the **max wheel RPM**, not the
 *     raw DC motor RPM. For JGB37-3530 the gearbox output is ~178 RPM,
 *     so we use a safe limit like:
 *        #define MOTOR_MAX_RPM 150.0f   // wheel shaft RPM
 *  6) Direction / polarity:
 *        ENCODER_POLARITY_MAP = { 0, ±1, ±1, ±1, ±1 }
 *     is used so that a "forward" command (e.g. +RPM) results in
 *     **positive encoder ticks** for all four wheels, even though
 *     physically the left and right sides spin in opposite directions
 *     in a skid-steer robot.
 *     If a wheel reports negative ticks when driving forward, flip its
 *     sign in ENCODER_POLARITY_MAP for that motor.
 *  TL;DR:
 *    - We model everything in **wheel space** (RPM, m/s).
 *    - ENCODER_TICKS_REV is calibrated from real measurement (~3600).
 *    - Gear ratio and insane motor RPM (~10k) are not used directly.
 *    - This keeps PID, odometry, and ROS integration simple and correct.
 * =========================================================== */
