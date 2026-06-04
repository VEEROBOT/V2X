#ifndef DEBUG_LOG_H
#define DEBUG_LOG_H

#include "usbd_cdc_if.h"
#include "main.h"
#include <stdio.h>
#include <stdarg.h>

typedef enum {
    LOG_LEVEL_INFO = 0,
    LOG_LEVEL_WARN,
    LOG_LEVEL_ERROR
} LogLevel;

// =======================================================
// Configure global log level before any include
// =======================================================
#define LOG_MIN_LEVEL   LOG_LEVEL_INFO
// #define LOG_MIN_LEVEL   LOG_LEVEL_WARN
//#define LOG_MIN_LEVEL   LOG_LEVEL_ERROR
// =======================================================

/**
 * @brief Send a formatted message to USB with timestamp and severity tag.
 */
void log_printf(LogLevel level, const char *fmt, ...);

/**
 * @brief Shorthand macros for different levels.
 */
#if LOG_MIN_LEVEL <= LOG_LEVEL_INFO
#define LOGI(fmt, ...)   log_printf(LOG_LEVEL_INFO, fmt, ##__VA_ARGS__)
#else
#define LOGI(fmt, ...)   ((void)0)
#endif

#if LOG_MIN_LEVEL <= LOG_LEVEL_WARN
#define LOGW(fmt, ...)   log_printf(LOG_LEVEL_WARN, fmt, ##__VA_ARGS__)
#else
#define LOGW(fmt, ...)   ((void)0)
#endif

#if LOG_MIN_LEVEL <= LOG_LEVEL_ERROR
#define LOGE(fmt, ...)   log_printf(LOG_LEVEL_ERROR, fmt, ##__VA_ARGS__)
#else
#define LOGE(fmt, ...)   ((void)0)
#endif

#endif // DEBUG_LOG_H
