#include "drivers/oled_ssd1306.h"
#include <string.h>

static I2C_HandleTypeDef *_hi2c;
static uint8_t _buffer[SSD1306_WIDTH * SSD1306_HEIGHT / 8];
static uint8_t _cursor_x = 0, _cursor_y = 0;

static void _cmd(uint8_t c)
{
    uint8_t buf[2] = {0x00, c};
    HAL_I2C_Master_Transmit(_hi2c, SSD1306_ADDR, buf, 2, 10);
}

bool oled_init(I2C_HandleTypeDef *hi2c)
{
    _hi2c = hi2c;
    HAL_Delay(100);

    if (HAL_I2C_IsDeviceReady(_hi2c, SSD1306_ADDR, 3, 10) != HAL_OK) {
        return false;
    }

    // Init sequence for 128x32
    _cmd(0xAE); // display off
    _cmd(0xD5); _cmd(0x80);
    _cmd(0xA8); _cmd(0x1F); // multiplex 32
    _cmd(0xD3); _cmd(0x00);
    _cmd(0x40);
    _cmd(0x8D); _cmd(0x14); // charge pump
    _cmd(0x20); _cmd(0x00); // horizontal addressing
    _cmd(0xA1);             // segment remap
    _cmd(0xC8);             // COM scan dec
    _cmd(0xDA); _cmd(0x02);
    _cmd(0x81); _cmd(0x8F);
    _cmd(0xD9); _cmd(0xF1);
    _cmd(0xDB); _cmd(0x40);
    _cmd(0xA4);
    _cmd(0xA6);             // normal display
    _cmd(0xAF);             // display on

    oled_clear();
    oled_display();
    return true;
}

void oled_clear(void)
{
    memset(_buffer, 0, sizeof(_buffer));
    _cursor_x = 0;
    _cursor_y = 0;
}

void oled_fill(uint8_t color)
{
    memset(_buffer, color ? 0xFF : 0x00, sizeof(_buffer));
}

void oled_display(void)
{
    _cmd(0x21); _cmd(0); _cmd(127);
    _cmd(0x22); _cmd(0); _cmd(3);

    // Send buffer in chunks
    for (uint16_t i = 0; i < sizeof(_buffer); i += 16) {
        uint8_t buf[17];
        buf[0] = 0x40;
        memcpy(&buf[1], &_buffer[i], 16);
        HAL_I2C_Master_Transmit(_hi2c, SSD1306_ADDR, buf, 17, 10);
    }
}

void oled_draw_pixel(uint8_t x, uint8_t y, uint8_t color)
{
    if (x >= SSD1306_WIDTH || y >= SSD1306_HEIGHT) return;

    if (color)
        _buffer[x + (y / 8) * SSD1306_WIDTH] |= (1 << (y & 7));
    else
        _buffer[x + (y / 8) * SSD1306_WIDTH] &= ~(1 << (y & 7));
}

void oled_fill_rect(uint8_t x, uint8_t y, uint8_t w, uint8_t h, uint8_t color)
{
    for (uint8_t i = 0; i < w; i++) {
        for (uint8_t j = 0; j < h; j++) {
            oled_draw_pixel(x + i, y + j, color);
        }
    }
}

void oled_set_cursor(uint8_t x, uint8_t y)
{
    _cursor_x = x;
    _cursor_y = y;
}

char oled_write_char(char ch, FontDef_t font, uint8_t color)
{
    if (ch < 32 || ch > 126) return 0;

    // Check bounds
    if (_cursor_x + font.FontWidth > SSD1306_WIDTH) {
        _cursor_x = 0;
        _cursor_y += font.FontHeight;
    }
    if (_cursor_y + font.FontHeight > SSD1306_HEIGHT) {
        return 0;
    }

    // Draw character
    for (uint8_t row = 0; row < font.FontHeight; row++) {
        uint16_t rowData = font.data[(ch - 32) * font.FontHeight + row];

        for (uint8_t col = 0; col < font.FontWidth; col++) {
            // Bit is MSB first
            if (rowData & (0x8000 >> col)) {
                oled_draw_pixel(_cursor_x + col, _cursor_y + row, color);
            } else {
                oled_draw_pixel(_cursor_x + col, _cursor_y + row, !color);
            }
        }
    }

    _cursor_x += font.FontWidth;
    return ch;
}

char oled_write_string(const char *str, FontDef_t font, uint8_t color)
{
    while (*str) {
        if (oled_write_char(*str, font, color) == 0) {
            return *str;  // couldn't write
        }
        str++;
    }
    return *str;
}

void oled_write_string_centered(const char *str, FontDef_t font, uint8_t y, uint8_t color)
{
    uint16_t len = strlen(str);
    uint16_t width = len * font.FontWidth;
    uint8_t x = (SSD1306_WIDTH - width) / 2;

    oled_set_cursor(x, y);
    oled_write_string(str, font, color);
}
