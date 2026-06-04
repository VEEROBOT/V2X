#include "app/app_transport.h"
#include "config/robot_config.h"
#include "app/debug_log.h"
#include "app/lyra_proto.h"
#include "rc/rc_ibus.h"
#include "usart.h"
#include <string.h>
#include <stdio.h>

static char     usb_line_buf[USB_CMD_MAX_LEN];
static uint16_t usb_line_len        = 0;
static volatile bool usb_line_ready = false;

extern LyraProtoParser_t g_lyra_parser;

void transport_usb_on_rx(const uint8_t *data, uint32_t len)
{
    if (usb_line_ready) {
        // previous line not yet consumed, drop new data for now
        return;
    }

    for (uint32_t i = 0; i < len; i++) {
        uint8_t b = data[i];
        char    c = (char)b;

        // ---- 1) Feed Lyra binary protocol parser ----
        LyraProtoPacket_t pkt;
        if (lyra_proto_parser_feed(&g_lyra_parser, b, &pkt)) {
            // Full, CRC-valid binary packet received
            lyra_proto_handle_packet(&pkt);
            // We don't "consume" these bytes from the text line buffer;
            // host should not mix binary and ASCII on the same stream.
        }

        // ---- 2) ASCII line handling (for CLI) ----
        if (c == '\r' || c == '\n') {
            if (usb_line_len > 0) {
                // terminate line
                if (usb_line_len < (USB_CMD_MAX_LEN - 1)) {
                    usb_line_buf[usb_line_len] = '\0';
                } else {
                    usb_line_buf[USB_CMD_MAX_LEN - 1] = '\0';
                }

                // debug: show what raw line we captured
                char dbg[96];
                snprintf(dbg, sizeof(dbg), "RX_RAW: '%s'\r\n", usb_line_buf);
                LOGI("%s", dbg);

                usb_line_ready = true;
                usb_line_len   = 0;
            }
        } else {
            if (usb_line_len < (USB_CMD_MAX_LEN - 1)) {
                usb_line_buf[usb_line_len++] = c;
            }
            // else: overflow → ignore extra chars
        }
    }
}

bool transport_usb_get_line(char *out_buf, uint16_t max_len)
{
    if (!usb_line_ready) {
        return false;
    }

    // copy safely
    strncpy(out_buf, usb_line_buf, max_len - 1);
    out_buf[max_len - 1] = '\0';

    usb_line_ready = false;
    return true;
}

/**
 * @brief Unified transmit: always UART5, optionally USB CDC
 */
void transport_write(const char *buf, uint16_t len)
{
    if (!buf || len == 0) return;

    switch (g_transport_target) {
        case TRANSPORT_USB:
            if (USB_CDC_IsReady())
                USB_Send((uint8_t *)buf, len);
            break;

        case TRANSPORT_UART3:
            HAL_UART_Transmit_DMA(&huart3, (uint8_t*)buf, len);
            break;

        case TRANSPORT_BOTH:
            if (USB_CDC_IsReady())
                USB_Send((uint8_t *)buf, len);
            HAL_UART_Transmit_DMA(&huart3, (uint8_t*)buf, len);
            break;

        default:
            break;
    }
}

/**
 * @brief Redirect printf() → transport_write()
 */
int _write(int file, char *data, int len)
{
    transport_write(data, len);
    return len;
}


// =====================================================
// UART3 RX transport handler (ROS2 / Lyra binary bridge)
// =====================================================
static char     uart3_line_buf[USB_CMD_MAX_LEN];
static uint16_t uart3_line_len        = 0;
static volatile bool uart3_line_ready = false;

void transport_uart_on_rx(const uint8_t *data, uint32_t len)
{
    if (!data || len == 0) return;

    for (uint32_t i = 0; i < len; i++) {
        uint8_t b = data[i];
        LyraProtoPacket_t pkt;

        // Feed binary protocol parser
        if (lyra_proto_parser_feed(&g_lyra_parser, b, &pkt)) {
            lyra_proto_handle_packet(&pkt);
            continue;
        }

        // Optional: accumulate ASCII for debugging (not critical)
        char c = (char)b;
        if (c == '\r' || c == '\n') {
            if (uart3_line_len > 0) {
                uart3_line_buf[uart3_line_len] = '\0';
                LOGI("[UART3] RX_RAW: '%s'\r\n", uart3_line_buf);
                uart3_line_ready = true;
                uart3_line_len = 0;
            }
        } else if (uart3_line_len < (USB_CMD_MAX_LEN - 1)) {
            uart3_line_buf[uart3_line_len++] = c;
        }
    }
}

bool transport_uart_get_line(char *out_buf, uint16_t max_len)
{
    if (!uart3_line_ready) return false;
    strncpy(out_buf, uart3_line_buf, max_len - 1);
    out_buf[max_len - 1] = '\0';
    uart3_line_ready = false;
    return true;
}
