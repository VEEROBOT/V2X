#ifndef INC_DRIVERS_SYSTEM_STATUS_H_
#define INC_DRIVERS_SYSTEM_STATUS_H_

#include "main.h"

// LED status colors
typedef enum {
    STATUS_OFF = 0,
    STATUS_OK,
    STATUS_ERROR,
    STATUS_INIT,
    STATUS_IMU,
    STATUS_DEBUG
} SystemStatus_t;

void SystemStatus_Init(void);
void SystemStatus_Set(SystemStatus_t status);
void SystemStatus_Task(void);  // optional periodic update

#endif /* INC_DRIVERS_SYSTEM_STATUS_H_ */
