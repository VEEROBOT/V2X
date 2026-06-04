#ifndef OLED_SSD1306_H
#define OLED_SSD1306_H

#include "stm32f4xx_hal.h"
#include "drivers/fonts.h"
#include <stdint.h>
#include <stdbool.h>

#define SSD1306_WIDTH   128
#define SSD1306_HEIGHT  32
#define SSD1306_ADDR    0x78  // 0x3C << 1

// Colors
#define SSD1306_BLACK   0
#define SSD1306_WHITE   1

bool oled_init(I2C_HandleTypeDef *hi2c);
void oled_clear(void);
void oled_fill(uint8_t color);
void oled_display(void);
void oled_set_cursor(uint8_t x, uint8_t y);
void oled_draw_pixel(uint8_t x, uint8_t y, uint8_t color);
void oled_fill_rect(uint8_t x, uint8_t y, uint8_t w, uint8_t h, uint8_t color);

// Text functions with font selection
char oled_write_char(char ch, FontDef_t font, uint8_t color);
char oled_write_string(const char *str, FontDef_t font, uint8_t color);

// Convenience: centered text
void oled_write_string_centered(const char *str, FontDef_t font, uint8_t y, uint8_t color);

#endif
