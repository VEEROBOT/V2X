// Core/Src/app/config_storage.c
#include "app/config_storage.h"
#include "config/robot_config.h"
#include "app/debug_log.h"
#include <string.h>

config_t g_config;
static volatile ConfigWriteState_t cfg_write_state = CONFIG_WRITE_IDLE;
static uint32_t cfg_write_request_time = 0;

// ========================= CRC32 helper ========================= //
static uint32_t cfg_calc_crc32(const uint8_t *data, uint32_t len)
{
    uint32_t crc = 0xFFFFFFFFu;

    for (uint32_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (int j = 0; j < 8; j++) {
            if (crc & 1u)
                crc = (crc >> 1) ^ 0xEDB88320u;
            else
                crc >>= 1;
        }
    }
    return ~crc;
}

// ========================= Defaults ========================= //

void config_reset_to_defaults(void)
{
    memset(&g_config, 0, sizeof(g_config));

    g_config.magic   = CONFIG_MAGIC;
    g_config.version = CONFIG_VERSION;

    // PID defaults per motor
    for (int i = 0; i < 4; i++) {
        g_config.kp[i] = PID_KP_DEFAULT;
        g_config.ki[i] = PID_KI_DEFAULT;
        g_config.kd[i] = PID_KD_DEFAULT;
    }

    // Encoder / kinematics
    g_config.cpr        = ENC_RESOLUTION_CPR;   // wheel counts per rev
    g_config.gear_ratio = GEAR_RATIO;

    // Default wheel direction (example: left negative, right positive)
    g_config.wheel_dir[0] = -1;   // M1
    g_config.wheel_dir[1] = -1;   // M2
    g_config.wheel_dir[2] = +1;   // M3
    g_config.wheel_dir[3] = +1;   // M4

    // Limits / network
    g_config.max_rad_s = 10.0f;   // safe default
    g_config.node_id   = 1;
    g_config.can_baud  = 1000000; // 1 Mbps

    // RC channel mapping defaults (iBus standard)
    g_config.rc_ch_throttle = 1;  // CH2
    g_config.rc_ch_steering = 3;  // CH4
    g_config.rc_ch_arm      = 4;  // CH5

    g_config.default_transport = 1;  // 0=USB, 1=UART3, 2=BOTH

    // Fill CRC
    g_config.crc = cfg_calc_crc32((const uint8_t*)&g_config,
                                  sizeof(config_t) - sizeof(uint32_t));
}

// ========================= Flash I/O helpers ========================= //

static bool cfg_flash_read(config_t *out)
{
    const config_t *flash_cfg = (const config_t *)CONFIG_FLASH_SECTOR_ADDR;

    // Copy raw bytes from flash
    memcpy(out, flash_cfg, sizeof(config_t));

    // Validate magic
    if (out->magic != CONFIG_MAGIC) {
        return false;
    }

    // Validate CRC
    uint32_t crc_calc = cfg_calc_crc32((const uint8_t*)out,
                                       sizeof(config_t) - sizeof(uint32_t));
    return (crc_calc == out->crc);
}

static void cfg_flash_write(const config_t *cfg)
{
    HAL_FLASH_Unlock();

    // Erase one sector (Sector 11 for F405)
    FLASH_EraseInitTypeDef erase;
    uint32_t erase_err = 0;

    erase.TypeErase    = FLASH_TYPEERASE_SECTORS;
    erase.Sector       = FLASH_SECTOR_11;      // sector index for 0x080E0000
    erase.NbSectors    = 1;
    erase.VoltageRange = FLASH_VOLTAGE_RANGE_3;

    if (HAL_FLASHEx_Erase(&erase, &erase_err) != HAL_OK) {
    	LOGE("CONFIG: FLASH ERASE ERROR = %lu", erase_err);
        HAL_FLASH_Lock();
        return;
    }

    // Program 32-bit words
    const uint32_t *p = (const uint32_t*)cfg;
    uint32_t addr = CONFIG_FLASH_SECTOR_ADDR;

    for (uint32_t i = 0; i < (sizeof(config_t) / 4u); i++) {
        if (HAL_FLASH_Program(FLASH_TYPEPROGRAM_WORD, addr, p[i]) != HAL_OK) {
        	LOGE("CONFIG: FLASH PROGRAM ERROR @0x%08lX", addr);
            break;
        }
        addr += 4u;
    }

    HAL_FLASH_Lock();
}

// ========================= Public API ========================= //

void config_init(void)
{
    config_t tmp;

    if (cfg_flash_read(&tmp)) {
        // Valid config in flash → adopt it
        memcpy(&g_config, &tmp, sizeof(g_config));
        LOGI("CONFIG: Loaded from flash (v%lu)", g_config.version);
    } else {
        // No valid config: use defaults
        config_reset_to_defaults();
        LOGI("CONFIG: Defaults loaded (no valid flash)");
    }
}

void config_save(void)
{
    // Recompute CRC before writing
    g_config.crc = cfg_calc_crc32((const uint8_t*)&g_config,
                                  sizeof(config_t) - sizeof(uint32_t));

    cfg_flash_write(&g_config);
    LOGI("CONFIG: Saved to flash");
}

const config_t* config_get(void)
{
    return &g_config;
}

void config_print(void)
{
    // Print PID gains (split into 3 lines to avoid buffer overflow)
    LOGI("CFG: PID Kp[%.3f %.3f %.3f %.3f]",
         g_config.kp[0], g_config.kp[1], g_config.kp[2], g_config.kp[3]);

    LOGI("CFG: PID Ki[%.3f %.3f %.3f %.3f]",
         g_config.ki[0], g_config.ki[1], g_config.ki[2], g_config.ki[3]);

    LOGI("CFG: PID Kd[%.3f %.3f %.3f %.3f]",
         g_config.kd[0], g_config.kd[1], g_config.kd[2], g_config.kd[3]);

    // Print encoder/kinematics
    LOGI("CFG: CPR=%ld, Gear=%.2f, WheelDir=[%d %d %d %d]",
         (long)g_config.cpr, g_config.gear_ratio,
         g_config.wheel_dir[0], g_config.wheel_dir[1],
         g_config.wheel_dir[2], g_config.wheel_dir[3]);

    // Print limits/network
    LOGI("CFG: max_rad_s=%.2f, CAN node=%u, baud=%lu",
         g_config.max_rad_s, g_config.node_id,
         (unsigned long)g_config.can_baud);

    // Print RC mapping and transport
    const char *transport_names[] = {"USB", "UART3", "BOTH"};
    LOGI("CFG: RC=[CH%u,CH%u,CH%u] Transport=%s",
         g_config.rc_ch_throttle,
         g_config.rc_ch_steering,
         g_config.rc_ch_arm,
         transport_names[g_config.default_transport]);
}

// ================================================================
// 🧠 Deferred Flash Write System (v2.2 – stable, self-healing)
// ================================================================

void config_request_save(void)
{
	if (system_armed) {
	    LOGW("CONFIG: Save requested while ARMED (state=%d) - deferring", cfg_write_state);
	} else {
	    LOGI("CONFIG: Save req (state=%d)", cfg_write_state);
	}

    if (system_armed) {
    	LOGW("CONFIG: Save ignored (system armed)");
        return;
    }

    if (cfg_write_state != CONFIG_WRITE_IDLE &&
        cfg_write_state != CONFIG_WRITE_DONE) {
    	LOGW("CONFIG: Save request ignored (busy)");
        return;
    }

    cfg_write_state = CONFIG_WRITE_PENDING;
    cfg_write_request_time = HAL_GetTick();
    // LOGI("CONFIG: Deferred save requested");
}

void config_process_deferred_write(void)
{
    switch (cfg_write_state)
    {
        case CONFIG_WRITE_PENDING:
            if ((HAL_GetTick() - cfg_write_request_time) > 500) {
                cfg_write_state = CONFIG_WRITE_IN_PROGRESS;
                LOGI("CONFIG: Write starting...");

                g_config.crc = cfg_calc_crc32(
                    (const uint8_t*)&g_config,
                    sizeof(config_t) - sizeof(uint32_t));

                config_save();

                cfg_write_state = CONFIG_WRITE_DONE;
                cfg_write_request_time = HAL_GetTick();
                LOGI("CONFIG: Deferred write completed");
            }
            break;

        case CONFIG_WRITE_DONE:
            // Immediately reset to IDLE after reporting
            cfg_write_state = CONFIG_WRITE_IDLE;
            break;

        default:
            break;
    }
}


/**
 * @brief Returns true if a deferred save is waiting to be processed.
 */
bool config_is_save_pending(void)
{
    return (cfg_write_state == CONFIG_WRITE_PENDING);
}

/**
 * @brief Lightweight idle hook callback to optionally wake config task.
 * For now, does nothing (placeholder for future signaling).
 */
void config_check_deferred_flag(void)
{
    // Currently no-op, but could be used to wake the TaskConfigWrite later.
}
