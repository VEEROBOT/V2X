#include "drivers/motor_driver.h"
#include "tim.h"
#include "gpio.h"
#include <stdlib.h>

extern TIM_HandleTypeDef htim3, htim5, htim12;
static const int8_t motor_direction_map[5] = MOTOR_DIRECTION_MAP;
static const uint8_t motor_map[5] = MOTOR_MAP;

// Fault status tracking (global, accessible from app_main)
MotorStatus_t motor_status[5] = {0};

/**
 * @brief Read fault pin state for a specific motor
 * @param motor Logical motor ID (1-4)
 * @return 1 if fault detected, 0 if normal
 */
static uint8_t Motor_ReadFaultPin(MotorID_t motor) {
    uint8_t physical_motor = motor_map[motor];
    GPIO_TypeDef* port;
    uint16_t pin;

    switch(physical_motor) {
        case 1: port = M1_FAULT_PORT; pin = M1_FAULT_PIN; break;
        case 2: port = M2_FAULT_PORT; pin = M2_FAULT_PIN; break;
        case 3: port = M3_FAULT_PORT; pin = M3_FAULT_PIN; break;
        case 4: port = M4_FAULT_PORT; pin = M4_FAULT_PIN; break;
        default: return 0;
    }

    uint8_t pin_state = HAL_GPIO_ReadPin(port, pin);

    // DRV8874 nFAULT is active-low
    return (pin_state == GPIO_PIN_RESET) ? 1 : 0;
}

/**
 * @brief Force a motor's PWM outputs to zero immediately
 * @param motor Logical motor ID (1-4)
 * @note Used for emergency stop and fault handling
 */
static void Motor_ForceStop(MotorID_t motor) {
    if (motor < MOTOR_1 || motor > MOTOR_4) return;

    uint8_t physical_motor = motor_map[motor];

    switch (physical_motor) {
        case 1:
            __HAL_TIM_SET_COMPARE(M1_PWM_TIMER, M1_PWM_CH1, 0);
            __HAL_TIM_SET_COMPARE(M1_PWM_TIMER, M1_PWM_CH2, 0);
            break;
        case 2:
            __HAL_TIM_SET_COMPARE(M2_PWM_TIMER, M2_PWM_CH1, 0);
            __HAL_TIM_SET_COMPARE(M2_PWM_TIMER, M2_PWM_CH2, 0);
            break;
        case 3:
            __HAL_TIM_SET_COMPARE(M3_PWM_TIMER, M3_PWM_CH1, 0);
            __HAL_TIM_SET_COMPARE(M3_PWM_TIMER, M3_PWM_CH2, 0);
            break;
        case 4:
            __HAL_TIM_SET_COMPARE(M4_PWM_TIMER, M4_PWM_CH1, 0);
            __HAL_TIM_SET_COMPARE(M4_PWM_TIMER, M4_PWM_CH2, 0);
            break;
    }
}

/**
 * @brief Initialize motor driver system
 * @note CubeMX already configures GPIO pins, we just need to:
 *       1. Enable motor driver (nSLEEP high)
 *       2. Start PWM timers
 *       3. Initialize fault status
 */
void Motor_Init(void) {
    // Enable motor driver chip (active high)
    HAL_GPIO_WritePin(MOTOR_NSLEEP_PORT, MOTOR_NSLEEP_PIN, GPIO_PIN_SET);
    HAL_Delay(10);  // Wait for driver to wake up

    // Start all PWM channels at 0% duty
    HAL_TIM_PWM_Start(M1_PWM_TIMER, M1_PWM_CH1);
    HAL_TIM_PWM_Start(M1_PWM_TIMER, M1_PWM_CH2);
    HAL_TIM_PWM_Start(M2_PWM_TIMER, M2_PWM_CH1);
    HAL_TIM_PWM_Start(M2_PWM_TIMER, M2_PWM_CH2);
    HAL_TIM_PWM_Start(M3_PWM_TIMER, M3_PWM_CH1);
    HAL_TIM_PWM_Start(M3_PWM_TIMER, M3_PWM_CH2);
    HAL_TIM_PWM_Start(M4_PWM_TIMER, M4_PWM_CH1);
    HAL_TIM_PWM_Start(M4_PWM_TIMER, M4_PWM_CH2);

    // Initialize all motors to stopped state with no faults
    for(int i = MOTOR_1; i <= MOTOR_4; i++) {
        motor_status[i].fault_type = MOTOR_FAULT_NONE;
        motor_status[i].is_faulted = 0;
        motor_status[i].fault_timestamp = 0;
        motor_status[i].fault_count = 0;
        Motor_ForceStop((MotorID_t)i);
    }
}

/**
 * @brief Check for motor fault condition with debouncing
 * @param motor Logical motor ID (1-4)
 * @return 1 if fault detected and latched, 0 otherwise
 * @note Uses debouncing to avoid false triggers from EMI/noise
 * @note DRV8874 nFAULT is active during: overcurrent, overtemp, undervoltage
 */
uint8_t Motor_CheckFault(MotorID_t motor) {
    if (motor < MOTOR_1 || motor > MOTOR_4) return 0;

    static uint32_t fault_debounce_start[5] = {0};
    static uint8_t fault_pending[5] = {0};
    uint32_t now = HAL_GetTick();

    uint8_t fault_pin_active = Motor_ReadFaultPin(motor);

    if (fault_pin_active) {
        // Fault pin is active (low)
        if (!fault_pending[motor]) {
            // First detection - start debounce timer
            fault_debounce_start[motor] = now;
            fault_pending[motor] = 1;
        } else {
            // Fault still active - check if debounce time elapsed
            if ((now - fault_debounce_start[motor]) >= FAULT_DEBOUNCE_MS) {
                // Valid fault confirmed after debounce period
                if (!motor_status[motor].is_faulted) {
                    // New fault - latch it
                    motor_status[motor].is_faulted = 1;
                    motor_status[motor].fault_timestamp = now;
                    motor_status[motor].fault_count++;

                    // Determine fault type based on DRV8874 behavior
                    // Note: DRV8874 uses single nFAULT pin for all fault types
                    // Most common cause is overcurrent
                    motor_status[motor].fault_type = MOTOR_FAULT_OVERCURRENT;

                    // Immediately stop this motor for safety
                    Motor_ForceStop(motor);
                }
                return 1;
            }
        }
    } else {
        // Fault pin is inactive (high) - normal operation
        fault_pending[motor] = 0;

        // Auto-clear fault if pin returns to normal
        // This allows automatic recovery after transient faults
        if (motor_status[motor].is_faulted) {
            motor_status[motor].is_faulted = 0;
            motor_status[motor].fault_type = MOTOR_FAULT_NONE;
        }
    }

    return motor_status[motor].is_faulted;
}

/**
 * @brief Set motor speed with direction
 * @param motor Logical motor ID (1-4)
 * @param speed Speed value (-100 to +100)
 *              Positive = forward, Negative = reverse, 0 = brake
 * @note Automatically blocks commands to faulted motors (fail-safe)
 * @note Applies direction mapping for skid-steer configuration
 */
void Motor_SetSpeed(MotorID_t motor, int16_t speed) {
    // Validate motor ID
    if (motor < MOTOR_1 || motor > MOTOR_4) return;

    // FAIL-SAFE: Force stop if motor is faulted
    // This ensures faulted motors cannot be commanded
    if (motor_status[motor].is_faulted) {
        Motor_ForceStop(motor);
        return;
    }

    // Apply direction mapping for skid-steer configuration
    int16_t directed_speed = speed * motor_direction_map[motor];

    // Scale from logical range (-100..+100) to PWM range (-4199..+4199)
    int16_t pwm_output = (int16_t)((directed_speed * PWM_MAX) / MOTOR_SPEED_RANGE);

    // Clamp to valid PWM range
    if (pwm_output > PWM_MAX) pwm_output = PWM_MAX;
    if (pwm_output < -PWM_MAX) pwm_output = -PWM_MAX;

    uint16_t duty = abs(pwm_output);
    uint8_t physical_motor = motor_map[motor];

    // Apply PWM to H-bridge channels
    // Forward: CH1 = duty, CH2 = 0
    // Reverse: CH1 = 0, CH2 = duty
    // Brake:   CH1 = 0, CH2 = 0
    switch (physical_motor) {
        case 1:
            __HAL_TIM_SET_COMPARE(M1_PWM_TIMER, M1_PWM_CH1, (pwm_output >= 0) ? duty : 0);
            __HAL_TIM_SET_COMPARE(M1_PWM_TIMER, M1_PWM_CH2, (pwm_output < 0) ? duty : 0);
            break;
        case 2:
            __HAL_TIM_SET_COMPARE(M2_PWM_TIMER, M2_PWM_CH1, (pwm_output >= 0) ? duty : 0);
            __HAL_TIM_SET_COMPARE(M2_PWM_TIMER, M2_PWM_CH2, (pwm_output < 0) ? duty : 0);
            break;
        case 3:
            __HAL_TIM_SET_COMPARE(M3_PWM_TIMER, M3_PWM_CH1, (pwm_output >= 0) ? duty : 0);
            __HAL_TIM_SET_COMPARE(M3_PWM_TIMER, M3_PWM_CH2, (pwm_output < 0) ? duty : 0);
            break;
        case 4:
            __HAL_TIM_SET_COMPARE(M4_PWM_TIMER, M4_PWM_CH1, (pwm_output >= 0) ? duty : 0);
            __HAL_TIM_SET_COMPARE(M4_PWM_TIMER, M4_PWM_CH2, (pwm_output < 0) ? duty : 0);
            break;
    }
}

/**
 * @brief Get current fault status for a motor
 * @param motor Logical motor ID (1-4)
 * @return Fault type enum
 */
MotorFault_t Motor_GetFaultStatus(MotorID_t motor) {
    if (motor < MOTOR_1 || motor > MOTOR_4) return MOTOR_FAULT_UNKNOWN;
    return motor_status[motor].fault_type;
}

/**
 * @brief Clear all motor faults and reset driver
 * @note Cycles nSLEEP pin to reset DRV8874 internal fault latches
 * @note Only use after fixing the root cause of the fault!
 */
void Motor_ClearFaults(void) {
    // Power cycle the motor driver to clear internal fault latches
    HAL_GPIO_WritePin(MOTOR_NSLEEP_PORT, MOTOR_NSLEEP_PIN, GPIO_PIN_RESET);
    HAL_Delay(10);  // Hold in sleep for 10ms
    HAL_GPIO_WritePin(MOTOR_NSLEEP_PORT, MOTOR_NSLEEP_PIN, GPIO_PIN_SET);
    HAL_Delay(10);  // Wait for driver to wake up

    // Clear software fault status
    for(int i = MOTOR_1; i <= MOTOR_4; i++) {
        motor_status[i].is_faulted = 0;
        motor_status[i].fault_type = MOTOR_FAULT_NONE;
        // Don't reset fault_count - keep statistics
    }
}

/**
 * @brief Emergency stop all motors
 * @note Sets all PWM outputs to zero immediately
 * @note Does NOT disable the motor driver (use Motor_Shutdown for that)
 */
void Motor_AllStop(void) {
    // Stop all motors via API (respects fault checking)
    for (uint8_t i = MOTOR_1; i <= MOTOR_4; i++) {
        Motor_ForceStop((MotorID_t)i);
    }
}

/**
 * @brief Shutdown motor driver completely
 * @note Stops all motors and disables driver chip (low power mode)
 * @note Use for emergency shutdown or before system sleep
 */
void Motor_Shutdown(void) {
    Motor_AllStop();
    HAL_Delay(5);  // Allow PWM to settle
    HAL_GPIO_WritePin(MOTOR_NSLEEP_PORT, MOTOR_NSLEEP_PIN, GPIO_PIN_RESET);
}

/**
 * @brief Restart motor driver after shutdown
 * @note Re-enables driver and clears any latched faults
 */
void Motor_Restart(void) {
    HAL_GPIO_WritePin(MOTOR_NSLEEP_PORT, MOTOR_NSLEEP_PIN, GPIO_PIN_SET);
    HAL_Delay(10);  // Wait for driver to initialize
    Motor_ClearFaults();
}
