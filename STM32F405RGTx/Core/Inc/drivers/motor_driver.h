#ifndef MOTOR_DRIVER_H
#define MOTOR_DRIVER_H

#include "config/robot_config.h"
#include "app/debug_log.h"

/**
 * @brief Motor fault types (DRV8874 specific)
 */
typedef enum {
    MOTOR_FAULT_NONE = 0,
    MOTOR_FAULT_OVERCURRENT,      // Most common - excessive load current
    MOTOR_FAULT_OVERTEMP,         // Thermal shutdown
    MOTOR_FAULT_UNDERVOLTAGE,     // PVDD too low
    MOTOR_FAULT_OVERVOLTAGE,      // PVDD too high (rare)
    MOTOR_FAULT_UNKNOWN           // Fault detected but type unknown
} MotorFault_t;

/**
 * @brief Motor status structure
 * @note Tracks per-motor fault state and statistics
 */
typedef struct {
    MotorFault_t fault_type;    // Current fault type
    uint8_t is_faulted;         // 1 = faulted, 0 = normal
    uint32_t fault_timestamp;   // HAL_GetTick() when fault occurred
    uint32_t fault_count;       // Total faults since init
} MotorStatus_t;

// Public API
void Motor_Init(void);
void Motor_SetSpeed(MotorID_t motor, int16_t speed);
void Motor_AllStop(void);
void Motor_Shutdown(void);
void Motor_Restart(void);

// Fault management
uint8_t Motor_CheckFault(MotorID_t motor);
MotorFault_t Motor_GetFaultStatus(MotorID_t motor);
void Motor_ClearFaults(void);

// Global motor status array (1-indexed, [0] unused)
extern MotorStatus_t motor_status[5];

#endif /* MOTOR_DRIVER_H */
