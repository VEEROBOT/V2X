#include "drivers/imu_lsm6dsrtr.h"
#include "config/robot_config.h"
#include "app/debug_log.h"
#include "main.h"
#include "usbd_cdc_if.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

extern I2C_HandleTypeDef hi2c2;

static volatile bool imu_data_ready_flag = false;
static uint32_t last_imu_read_time = 0;
#define IMU_READ_INTERVAL_MS 10  // Read IMU at 100Hz

#define IMU_ADDR       (IMU_ADDR_7BIT << 1)
#define WHO_AM_I_REG   0x0F
#define CTRL1_XL       0x10
#define CTRL2_G        0x11
#define CTRL3_C        0x12
#define OUTX_L_G       0x22
#define OUTX_L_A       0x28

// ✅ INCREASED TIMEOUT: 10ms is safer for I2C during heavy RTOS load
#define IMU_I2C_TIMEOUT_MS  10

// Non-blocking read with reasonable timeout
static bool imu_i2c_read_nonblocking(uint8_t reg, uint8_t *buf, uint8_t len)
{
    // ✅ Use 10ms timeout instead of 2ms (prevents false timeouts)
    HAL_StatusTypeDef status = HAL_I2C_Mem_Read(IMU_I2C_BUS, IMU_ADDR, reg, 1, buf, len, IMU_I2C_TIMEOUT_MS);

    if (status != HAL_OK) {
        // ✅ On error, try to recover I2C bus once
        if (hi2c2.State == HAL_I2C_STATE_READY) {
            return false;  // Recoverable error
        }

        // Hard error - try reset
        __HAL_I2C_DISABLE(&hi2c2);
        HAL_Delay(1);
        __HAL_I2C_CLEAR_FLAG(&hi2c2, I2C_FLAG_AF | I2C_FLAG_ARLO | I2C_FLAG_BERR);
        __HAL_I2C_ENABLE(&hi2c2);
        return false;
    }

    return true;
}

// Original blocking versions (for initialization only)
static void imu_i2c_write_u8(uint8_t reg, uint8_t val)
{
    HAL_I2C_Mem_Write(IMU_I2C_BUS, IMU_ADDR, reg, 1, &val, 1, HAL_MAX_DELAY);
}

static void imu_i2c_read(uint8_t reg, uint8_t *buf, uint8_t len)
{
    HAL_I2C_Mem_Read(IMU_I2C_BUS, IMU_ADDR, reg, 1, buf, len, HAL_MAX_DELAY);
}

// I2C Bus Recovery Function
static void imu_i2c_recovery(void)
{
    __HAL_I2C_DISABLE(IMU_I2C_BUS);
    HAL_Delay(1);
    __HAL_I2C_CLEAR_FLAG(IMU_I2C_BUS, I2C_FLAG_AF | I2C_FLAG_ARLO | I2C_FLAG_BERR);
    __HAL_I2C_ENABLE(IMU_I2C_BUS);
    HAL_Delay(1);
}

void imu_init(void)
{
    HAL_Delay(100);

    uint8_t who = 0;
    int retry_count = 0;
    const int max_retries = 8;

    while (retry_count < max_retries) {
        if (HAL_I2C_Mem_Read(IMU_I2C_BUS, IMU_ADDR, WHO_AM_I_REG, 1, &who, 1, 100) == HAL_OK) {
            if (who == IMU_WHOAMI_EXPECTED) {
                break;
            }
        }

        retry_count++;

        char retry_msg[48];
        snprintf(retry_msg, sizeof(retry_msg), "IMU Retry %d/%d (WHO_AM_I: 0x%02X)\r\n",
                 retry_count, max_retries, who);
        LOGI("%s", retry_msg);

        if (retry_count % 2 == 0) {
            imu_i2c_recovery();
        }

        HAL_Delay(20 * retry_count);
    }

    char msg[64];
    sprintf(msg, "IMU WHO_AM_I: 0x%02X", who);
    LOGI("%s", msg);


    if (who != IMU_WHOAMI_EXPECTED)
    {
        sprintf(msg, "ERROR: IMU not detected! Expected 0x%02X", IMU_WHOAMI_EXPECTED);
        LOGI("%s", msg);
        return;
    }

    // Initialize accelerometer (104 Hz, ±2g)
    imu_i2c_write_u8(CTRL1_XL, 0x40);
    // Initialize gyroscope (104 Hz, ±2000 dps)
    imu_i2c_write_u8(CTRL2_G,  0x4C);
    // Enable auto-increment
    imu_i2c_write_u8(CTRL3_C,  0x44);

    last_imu_read_time = HAL_GetTick();

    LOGI("OK - IMU Initialized Successfully");
}

// Original blocking read (keep for compatibility)
void imu_read(imu_sample_t *data)
{
    uint8_t raw[6];
    int16_t gx, gy, gz, ax, ay, az;

    imu_i2c_read(OUTX_L_G, raw, 6);
    gx = (int16_t)(raw[1] << 8 | raw[0]);
    gy = (int16_t)(raw[3] << 8 | raw[2]);
    gz = (int16_t)(raw[5] << 8 | raw[4]);

    imu_i2c_read(OUTX_L_A, raw, 6);
    ax = (int16_t)(raw[1] << 8 | raw[0]);
    ay = (int16_t)(raw[3] << 8 | raw[2]);
    az = (int16_t)(raw[5] << 8 | raw[4]);

    const float gyro_sensitivity = (IMU_GYRO_FS_DPS == 2000.0f) ? 70.0f / 1000.0f : 35.0f / 1000.0f;
    const float accel_sensitivity = (IMU_ACC_FS_G == 2.0f) ? 0.061f / 1000.0f : 0.122f / 1000.0f;

    data->gx_dps = gx * gyro_sensitivity;
    data->gy_dps = gy * gyro_sensitivity;
    data->gz_dps = gz * gyro_sensitivity;
    data->ax_g   = ax * accel_sensitivity * 9.81f;
    data->ay_g   = ay * accel_sensitivity * 9.81f;
    data->az_g   = az * accel_sensitivity * 9.81f;
}

// ✅ IMPROVED: Non-blocking with better error handling
bool imu_read_nonblocking(imu_sample_t *data)
{
    if (!imu_data_ready_flag) {
        return false;
    }

    uint8_t raw[6];
    int16_t gx, gy, gz, ax, ay, az;

    // Read gyro with improved timeout
    if (!imu_i2c_read_nonblocking(OUTX_L_G, raw, 6)) {
        imu_data_ready_flag = false;
        return false;
    }

    gx = (int16_t)(raw[1] << 8 | raw[0]);
    gy = (int16_t)(raw[3] << 8 | raw[2]);
    gz = (int16_t)(raw[5] << 8 | raw[4]);

    // Read accel with improved timeout
    if (!imu_i2c_read_nonblocking(OUTX_L_A, raw, 6)) {
        imu_data_ready_flag = false;
        return false;
    }

    ax = (int16_t)(raw[1] << 8 | raw[0]);
    ay = (int16_t)(raw[3] << 8 | raw[2]);
    az = (int16_t)(raw[5] << 8 | raw[4]);

    const float gyro_sensitivity = (IMU_GYRO_FS_DPS == 2000.0f) ? 70.0f / 1000.0f : 35.0f / 1000.0f;
    const float accel_sensitivity = (IMU_ACC_FS_G == 2.0f) ? 0.061f / 1000.0f : 0.122f / 1000.0f;

    data->gx_dps = gx * gyro_sensitivity;
    data->gy_dps = gy * gyro_sensitivity;
    data->gz_dps = gz * gyro_sensitivity;
    data->ax_g   = ax * accel_sensitivity * 9.81f;
    data->ay_g   = ay * accel_sensitivity * 9.81f;
    data->az_g   = az * accel_sensitivity * 9.81f;

    imu_data_ready_flag = false;
    return true;
}

bool imu_data_ready(void)
{
    return imu_data_ready_flag;
}

void imu_update_timer(void)
{
    uint32_t now = HAL_GetTick();
    if ((now - last_imu_read_time) >= IMU_READ_INTERVAL_MS) {
        imu_data_ready_flag = true;
        last_imu_read_time = now;
    }
}
