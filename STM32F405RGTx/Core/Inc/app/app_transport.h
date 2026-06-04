#ifndef APP_TRANSPORT_H
#define APP_TRANSPORT_H

#include <stdint.h>
#include <stdbool.h>

#define USB_CMD_MAX_LEN   64   // max length of one command line

// Called from USB RX callback (ISR context-ish)
void transport_usb_on_rx(const uint8_t *data, uint32_t len);

// Called from TaskTransportRX (normal task)
// Returns true if one full line was available and copied into out_buf
bool transport_usb_get_line(char *out_buf, uint16_t max_len);
void transport_write(const char *buf, uint16_t len);
void transport_uart_on_rx(const uint8_t *data, uint32_t len);
bool transport_uart_get_line(char *out_buf, uint16_t max_len);

#endif  // APP_TRANSPORT_H
