// oled_display.h
#ifndef OLED_DISPLAY_H
#define OLED_DISPLAY_H

#include <stdbool.h>

void oled_app_init(void);
void oled_app_update(void);  // call periodically (e.g., from a task)

// Update status data
void oled_set_ip(const char *ip);
void oled_set_battery(float voltage, int percent);
void oled_set_mode(const char *mode);
void oled_set_ros_status(bool connected);

#endif
