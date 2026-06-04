#ifndef ADC_UTILS_H
#define ADC_UTILS_H

#include <stdint.h>
#include "config/robot_config.h"

void ADC_Utils_Init(void);
uint16_t ADC_Utils_GetRaw(uint8_t idx);
float ADC_Utils_GetBatteryVoltage(void);

extern uint16_t adc_buf[5];  // global DMA buffer

#endif // ADC_UTILS_H
