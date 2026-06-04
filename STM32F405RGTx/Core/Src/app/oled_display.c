// oled_display.c
#include "app/oled_display.h"
#include "drivers/oled_ssd1306.h"
#include "i2c.h"
#include <stdio.h>
#include <string.h>

#define PAGE_TIME_MS  3000
#define NUM_PAGES     3  // After splash, cycle pages 1-3

static bool _initialized = false;
static uint8_t _current_page = 0;
static uint32_t _last_switch = 0;

static char _ip[20] = "Domain ID: 115";
static float _bat_voltage = 0.0f;
static int _bat_percent = 0;
static char _mode[16] = "IDLE";
static char _version [16] = "Jazzy";
static bool _ros_connected = false;

// Page 0: BEETLEBOT splash - white bg, black text (shown once)
static void draw_page_splash(void)
{
    oled_fill(SSD1306_WHITE);

    // BEETLEBOT centered, using 11x18 font
    // 9 chars * 11 = 99px, center: (128-99)/2 = 14
    // Height 18px, center on 32: (32-18)/2 = 7
    oled_write_string_centered("BEETLEBOT", Font_11x18, 7, SSD1306_BLACK);

    oled_display();
}

// Page 1: IP Address
//static void draw_page_ip(void)
//{
//    oled_clear();
//
//    // "IP" big font centered at top
//    oled_write_string_centered("ID", Font_11x18, 0, SSD1306_WHITE);
//
//    // IP address smaller, centered below
//    oled_write_string_centered(_ip, Font_7x10, 22, SSD1306_WHITE);
//
//    oled_display();
//}

// Page 2: Battery
static void draw_page_battery(void)
{
    char line[24];
    oled_clear();

    // "BATTERY" big
    oled_write_string_centered("BATTERY", Font_11x18, 0, SSD1306_WHITE);

    // Voltage and percent
    snprintf(line, sizeof(line), "%05.2fV  %3d%%", _bat_voltage, _bat_percent);
    oled_write_string_centered(line, Font_7x10, 22, SSD1306_WHITE);

    oled_display();
}

// Page 3: ROS Status
static void draw_page_ros(void)
{
    char line[32];
    oled_clear();

    // "ROS" big
    oled_write_string_centered("ROS", Font_11x18, 0, SSD1306_WHITE);

    // Mode and link on two lines, smaller font
    snprintf(line, sizeof(line), "%s  %s", _version, _ros_connected ? "Jalisco" : "Jalisco");
    oled_write_string_centered(line, Font_7x10, 22, SSD1306_WHITE);

    oled_display();
}

void oled_app_init(void)
{
    if (oled_init(&hi2c2)) {
        _initialized = true;
        _current_page = 0;
        _last_switch = HAL_GetTick();
        draw_page_splash();
    }
}

void oled_app_update(void)
{
    if (!_initialized) return;

    uint32_t now = HAL_GetTick();

    if ((now - _last_switch) >= PAGE_TIME_MS) {
        _last_switch = now;

        // After splash (page 0), cycle only pages 1-3
        if (_current_page == 0) {
            _current_page = 1;
        } else {
            _current_page++;
            if (_current_page > NUM_PAGES) _current_page = 1;
        }

        switch (_current_page) {
            // case 1: draw_page_ip();      break;
            case 1: draw_page_battery(); break;
            case 2: draw_page_ros();     break;
        }
    }
}

void oled_set_ip(const char *ip)
{
    strncpy(_ip, ip, sizeof(_ip) - 1);
    _ip[sizeof(_ip) - 1] = '\0';
}

void oled_set_battery(float voltage, int percent)
{
    _bat_voltage = voltage;
    if (percent < 0) percent = 0;
    if (percent > 100) percent = 100;
    _bat_percent = percent;
}

void oled_set_mode(const char *mode)
{
    strncpy(_mode, mode, sizeof(_mode) - 1);
    _mode[sizeof(_mode) - 1] = '\0';
}

void oled_set_ros_status(bool connected)
{
    _ros_connected = connected;
}
