// Core/Inc/app/config_storage.h
#ifndef CONFIG_STORAGE_H
#define CONFIG_STORAGE_H

#include "stm32f4xx_hal.h"
#include <stdint.h>
#include <stdbool.h>

/**
 * Flash layout (STM32F405, 1MB Flash):
 *  - Sector 11: 0x080E0000 - 0x080FFFFF (128KB)
 * We reserve this sector exclusively for configuration.
 */
#define CONFIG_FLASH_SECTOR_ADDR  0x080E0000U

// Signature + version
#define CONFIG_MAGIC              0x43464721U   // "CFG!"
#define CONFIG_VERSION            0x00010001U   // v1.1

/**
 * Persistent controller configuration
 * Stored in internal flash with CRC32 protection.
 */
typedef struct {
    uint32_t magic;       // CONFIG_MAGIC
    uint32_t version;     // CONFIG_VERSION

    // PID gains per motor (M1..M4)
    float kp[4];
    float ki[4];
    float kd[4];

    // Encoder / kinematics
    int32_t cpr;          // counts per wheel revolution
    float   gear_ratio;   // gear ratio motor:wheel (for future use)
    int8_t  wheel_dir[4]; // +1 or -1 per motor

    // Limits & network
    float    max_rad_s;   // max wheel angular speed (rad/s)
    uint8_t  node_id;     // CAN node ID
    uint32_t can_baud;    // CAN baud rate (e.g. 500000, 1000000)

    // RC channel mapping (0–9 for iBus channels)
    uint8_t  rc_ch_throttle; // default = 1 (CH2)
    uint8_t  rc_ch_steering; // default = 3 (CH4)
    uint8_t  rc_ch_arm;      // default = 4 (CH5)

    uint8_t  default_transport;    // Default transport mode (0=USB, 1=UART3, 2=BOTH)

    // CRC32 over all fields except this
    uint32_t crc;
} config_t;

// Global config instance
extern config_t g_config;

// Public API
void        config_init(void);               // load from flash or defaults
void        config_save(void);               // save g_config to flash
void        config_reset_to_defaults(void);  // reset g_config, not saved
const config_t* config_get(void);            // read-only pointer
void        config_print(void);              // debug dump

// ================================================================
// 🧠 Deferred Flash Write Support (v2.1 upgrade)
// ================================================================

typedef enum {
    CONFIG_WRITE_IDLE = 0,         // no save pending
    CONFIG_WRITE_PENDING,          // user requested save
    CONFIG_WRITE_IN_PROGRESS,      // flash operation running
    CONFIG_WRITE_DONE              // completed successfully
} ConfigWriteState_t;

// Schedules a config save (non-blocking)
void config_request_save(void);

// To be called periodically (e.g., from vApplicationIdleHook or a low-priority task)
void config_process_deferred_write(void);
void config_check_deferred_flag(void);

// Returns true if a save is pending
bool config_is_save_pending(void);

#endif // CONFIG_STORAGE_H
