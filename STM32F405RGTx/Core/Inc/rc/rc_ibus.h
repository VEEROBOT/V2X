#pragma once
#include <stdint.h>
#include <stdbool.h>

#define IBUS_MAX_CHANNELS   10
#define IBUS_FRAME_SIZE     32
#define IBUS_TIMEOUT_MS     500   // fail-safe timeout

#define IBUS_RAW_BUF_SIZE   64    // for debugging: last 64 bytes

typedef struct {
    float ch[IBUS_MAX_CHANNELS];  // normalized -1..1
    uint16_t raw[IBUS_MAX_CHANNELS];
    uint32_t last_update_ms;
    bool valid;
} IBUS_State_t;

extern IBUS_State_t ibus_state;
extern volatile uint32_t ibus_rx_byte_count;

extern uint8_t ibus_raw_buf[IBUS_RAW_BUF_SIZE];
extern uint8_t ibus_raw_index;

void ibus_init(void);                    // init UART + buffers
void ibus_on_byte(uint8_t b);            // feed one byte from UART IRQ
void ibus_process_frame(uint8_t *buf);   // decode full iBus frame
void ibus_task_update(void);             // called periodically (20–50Hz)
bool rc_is_transmitter_active(void);
