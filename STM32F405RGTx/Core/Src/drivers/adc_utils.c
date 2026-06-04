#include "drivers/adc_utils.h"
#include "main.h"
#include "stm32f4xx_hal.h"

// ✅ Global DMA buffer to hold all 5 ADC channel readings
uint16_t adc_buf[5];

// External ADC handle from CubeMX
extern ADC_HandleTypeDef hadc1;

// Call once during system init
void ADC_Utils_Init(void)
{
    // Start continuous DMA conversion for 5 channels
    HAL_ADC_Start_DMA(&hadc1, (uint32_t *)adc_buf, 5);
}

// Get raw ADC value for a given channel index
uint16_t ADC_Utils_GetRaw(uint8_t idx)
{
    if (idx >= 5) return 0;
    return adc_buf[idx];
}

#define R1 47000.0f
#define R2 10000.0f
#define DIVIDER_RATIO ((R1 + R2) / R2)

// Read battery voltage (PA4 = ADC1_IN4 = index 4)
float ADC_Utils_GetBatteryVoltage(void)
{
    const float VREF = 3.3f;
    const float ADC_MAX = 4095.0f;

    // R1 = 47k, R2 = 10k → ratio = (R1 + R2) / R2 = 5.7
    // R1 = 33k, R2 = 10k → ratio = (R1 + R2) / R2 = 4.3
    // const float DIVIDER_RATIO = 5.7f;

    uint16_t raw_val = adc_buf[4];
    float voltage = ((float)raw_val / ADC_MAX) * VREF * DIVIDER_RATIO * BATTERY_CAL_FACTOR;

    return voltage;
}
