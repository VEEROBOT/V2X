#include "drivers/system_status.h"
#include "config/robot_config.h"
#include "app/debug_log.h"
#include <stdint.h>
#define BRIGHTNESS  20

/* ====== Simple 1-LED WS2812 driver using DWT-based precise timing ====== */

#define NS_TO_CYCLES(ns)  ((uint32_t)((ns) * (SYS_CORE_CLOCK_HZ / 1e9)))
#define WS_T0H_NS         300
#define WS_T1H_NS         600
#define WS_TOTAL_NS       1000

#define WS_T0H_CYCLES     NS_TO_CYCLES(WS_T0H_NS)
#define WS_T1H_CYCLES     NS_TO_CYCLES(WS_T1H_NS)
#define WS_TOTAL_CYCLES   NS_TO_CYCLES(WS_TOTAL_NS)

static inline void ws_delay(uint32_t cycles) {
    uint32_t start = DWT->CYCCNT;
    while ((DWT->CYCCNT - start) < cycles);
}

static void ws_send_byte(uint8_t byte) {
    for (int bit = 7; bit >= 0; bit--) {
        HAL_GPIO_WritePin(LED_PORT, LED_PIN, GPIO_PIN_SET);
        if (byte & (1 << bit))
            ws_delay(WS_T1H_CYCLES);
        else
            ws_delay(WS_T0H_CYCLES);

        HAL_GPIO_WritePin(LED_PORT, LED_PIN, GPIO_PIN_RESET);
        ws_delay(WS_TOTAL_CYCLES - ((byte & (1 << bit)) ? WS_T1H_CYCLES : WS_T0H_CYCLES));
    }
}

static void ws_show_color(uint8_t r, uint8_t g, uint8_t b) {
    __disable_irq();
    r = (r * BRIGHTNESS) / 255;
    g = (g * BRIGHTNESS) / 255;
    b = (b * BRIGHTNESS) / 255;
    ws_send_byte(g);
    ws_send_byte(r);
    ws_send_byte(b);
    __enable_irq();
    HAL_Delay(1); // reset >50 µs
}

/* ====== Public Interface ====== */

static SystemStatus_t current_status = STATUS_OFF;
static uint32_t blink_timer = 0;
static uint8_t blink_state = 0;

void SystemStatus_Init(void)
{
    // No JTAG remap needed for STM32F4 — CubeMX handles this via "Serial Wire"

    // Enable DWT counter for WS2812 precise timing
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;

    // Configure LED pin as output
    GPIO_InitTypeDef GPIO_InitStruct = {0};
    GPIO_InitStruct.Pin   = LED_PIN;               // PA15 per your config
    GPIO_InitStruct.Mode  = GPIO_MODE_OUTPUT_PP;
    GPIO_InitStruct.Pull  = GPIO_PULLDOWN;         // <— force idle low
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
    HAL_GPIO_Init(LED_PORT, &GPIO_InitStruct);

    HAL_GPIO_WritePin(LED_PORT, LED_PIN, GPIO_PIN_RESET);
    HAL_Delay(10);

    // Debug test: blink LED pin 5 times
    for (int i = 0; i < 5; i++) {
        HAL_GPIO_WritePin(LED_PORT, LED_PIN, GPIO_PIN_SET);
        HAL_Delay(100);
        HAL_GPIO_WritePin(LED_PORT, LED_PIN, GPIO_PIN_RESET);
        HAL_Delay(100);
    }

    // Reset LED line low
    HAL_GPIO_WritePin(LED_PORT, LED_PIN, GPIO_PIN_RESET);
    HAL_Delay(10);

    current_status = STATUS_OFF;

    for (int i = 0; i < 10; i++) {
      HAL_GPIO_WritePin(LED_PORT, LED_PIN, GPIO_PIN_SET);
      HAL_Delay(250);
      HAL_GPIO_WritePin(LED_PORT, LED_PIN, GPIO_PIN_RESET);
      HAL_Delay(250);
    }
}


void SystemStatus_Set(SystemStatus_t status)
{
    current_status = status;

    switch (status) {
        case STATUS_OFF:
            ws_show_color(0, 0, 0);
            break;
        case STATUS_OK:
            ws_show_color(0, 255, 0); // Green
            break;
        case STATUS_ERROR:
            ws_show_color(255, 0, 0); // Red
            break;
        case STATUS_INIT:
            ws_show_color(0, 0, 255); // White
            break;
        case STATUS_IMU:
            ws_show_color(0, 0, 255); // Blue
            break;
        case STATUS_DEBUG:
            ws_show_color(255, 255, 0); // Yellow
            break;
    }
}

void SystemStatus_Task(void)
{
    // Optional: blinking patterns
    uint32_t now = HAL_GetTick();

    if (current_status == STATUS_ERROR) {
        if (now - blink_timer >= 500) {
            blink_timer = now;
            blink_state = !blink_state;
            if (blink_state)
                ws_show_color(255, 0, 0);
            else
                ws_show_color(0, 0, 0);
        }
    }
}

