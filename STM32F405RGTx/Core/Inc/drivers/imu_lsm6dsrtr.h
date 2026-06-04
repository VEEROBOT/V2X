#ifndef IMU_LSM6DSRTR_H
#define IMU_LSM6DSRTR_H

#include "main.h"
#include <stdint.h>
#include <stdbool.h>

typedef struct {
    float ax_g, ay_g, az_g;    // Acceleration in m/s²
    float gx_dps, gy_dps, gz_dps; // Angular velocity in °/s
} imu_sample_t;

void imu_init(void);
void imu_read(imu_sample_t *data);
bool imu_read_nonblocking(imu_sample_t *data);
bool imu_data_ready(void);
void imu_update_timer(void);

#endif
