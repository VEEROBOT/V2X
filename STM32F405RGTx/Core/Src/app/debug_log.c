#include "app/debug_log.h"
#include "usbd_cdc_if.h"
#include "stm32f4xx_hal.h"
#include <stdarg.h>

void log_printf(LogLevel level, const char *fmt, ...)
{
    if (!USB_CDC_IsReady()) return;

    // Runtime check against LOG_MIN_LEVEL
    if (level < LOG_MIN_LEVEL) return;

    static const char *level_tags[] = {"[I]", "[W]", "[E]"};
    char buf[160];
    uint32_t ms = HAL_GetTick();

    int pos = snprintf(buf, sizeof(buf), "%s %8lu ", level_tags[level], ms);

    va_list args;
    va_start(args, fmt);
    pos += vsnprintf(buf + pos, sizeof(buf) - pos, fmt, args);
    va_end(args);

    if (pos > (int)sizeof(buf)) pos = sizeof(buf);

    // Add newline only if not already present
    if (pos >= 2) {
        if (buf[pos - 1] != '\n' && buf[pos - 2] != '\r') {
            if (pos < (int)(sizeof(buf) - 3)) {
                buf[pos++] = '\r';
                buf[pos++] = '\n';
            }
        }
    } else {
        buf[pos++] = '\r';
        buf[pos++] = '\n';
    }

    USB_Send((const uint8_t *)buf, pos);
}
