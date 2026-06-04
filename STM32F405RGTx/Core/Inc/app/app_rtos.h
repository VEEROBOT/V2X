// app/app_rtos.h
#ifndef APP_RTOS_H
#define APP_RTOS_H

#include "cmsis_os.h"

void app_rtos_init(void);

// Task prototypes
void TaskMotorControl(void *argument);
void TaskSafety(void *argument);
void TaskSensor(void *argument);
void TaskTelemetry(void *argument);
void TaskTransportRX(void *argument);

#endif
