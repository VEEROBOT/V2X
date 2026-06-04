// app/app_rtos.c
#include "app/config_storage.h"
#include "app/app_rtos.h"
#include "rc/rc_ibus.h"
#include "config/robot_config.h"
#include "app/debug_log.h"
#include "drivers/motor_driver.h"
#include "drivers/encoder_driver.h"
#include "drivers/imu_lsm6dsrtr.h"
#include "drivers/pid_controller.h"
#include "app/app_main.h"
#include "usbd_cdc_if.h"
#include "app/lyra_cmd.h"
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "app/app_transport.h"
#include <stdlib.h>
#include <ctype.h>
#include "app/lyra_proto.h"
#include "drivers/adc_utils.h"
#include "iwdg.h"
#include "app/oled_display.h"


// externs from app_main.c
extern PID_Controller_t pid_motor[5];
extern volatile float            target_rpm[5];
extern imu_sample_t     current_imu_data;
extern float            rpm_history[5][RPM_AVG_WINDOW];
extern uint8_t          rpm_index[5];
extern float            rpm_avg[5];
extern uint8_t          stall_cnt[5];
extern uint8_t          stall_latched[5];
extern MotorStatus_t    motor_status[5];
extern config_t 		g_config;
float batt_v;

static uint8_t watchdog_started = 0;

// ===== TASK IMPLEMENTATIONS =====

// ================================================================
// 🧠 TaskConfigWrite – low-priority background flash writer
// ================================================================
void TaskConfigWrite(void *argument)
{
    for (;;)
    {
        config_process_deferred_write();
        osDelay(50);  // check every 100 ms
    }
}

void TaskMotorControl(void *argument)
{
    for (;;)
    {

        if (!watchdog_started) {
            MX_IWDG_Init();  // ✅ Call the CubeMX-generated function
            watchdog_started = 1;
            LOGI("IWDG watchdog started (16.4s timeout)");
        }

        // ✅ Feed watchdog every loop
        HAL_IWDG_Refresh(&hiwdg);  // hiwdg is declared in iwdg.c

        // ✅ Update heartbeat
        last_control_loop_ms = HAL_GetTick();

        Encoder_Update();

        uint32_t now = HAL_GetTick();
        bool timeout = false;

        // Check for command timeout only when armed and we have a timestamp
        if (system_armed && (last_cmd_ms != 0)) {
            if ((now - last_cmd_ms) > CMD_TIMEOUT_MS) {
                timeout = true;
            }
        }

        for (int motor = MOTOR_1; motor <= MOTOR_4; motor++) {

            // 1) Global control OFF → calibration / free spin mode
            if (control_mode == CONTROL_MODE_OFF) {
                Motor_SetSpeed((MotorID_t)motor, 0);
                PID_Reset(&pid_motor[motor]);
                applied_rpm[motor] = 0.0f;
                target_rpm[motor]  = 0.0f;
                stall_cnt[motor]   = 0;
                stall_latched[motor] = 0;
                continue;
            }

            // 2) Disarmed or timeout → force safe stop
            if (!system_armed || timeout) {
                Motor_SetSpeed((MotorID_t)motor, 0);
                PID_Reset(&pid_motor[motor]);
                applied_rpm[motor] = 0.0f;
                target_rpm[motor]  = 0.0f;
                stall_cnt[motor]   = 0;
                stall_latched[motor] = 0;
                continue;
            }

            // 3) Normal closed-loop control (armed, not timed out)

            // Commanded RPM from higher-level commands (ALL/SKID)
            float cmd_rpm    = target_rpm[motor];

            // Ramped setpoint RPM that we actually feed into the PID
            float sp         = applied_rpm[motor];
            float actual_rpm = Encoder_GetRPM((MotorID_t)motor);

            // --- near-zero kill zone ---
            if (fabsf(cmd_rpm) < 1.0f && fabsf(actual_rpm) < 2.0f) {
                PID_Reset(&pid_motor[motor]);
                Motor_SetSpeed((MotorID_t)motor, 0);
                applied_rpm[motor] = 0.0f;
                continue;
            }

            // --- Setpoint ramp: limit how fast sp follows cmd_rpm ---
            float diff = cmd_rpm - sp;
            float step = MAX_RPM_STEP_PER_CYCLE;

            if (diff > step) {
                sp += step;
            } else if (diff < -step) {
                sp -= step;
            } else {
                sp = cmd_rpm;    // close enough; snap to target
            }

            applied_rpm[motor] = sp;

            // --- Stall detection uses ramped setpoint ---
            if (fabsf(sp) > 5.0f) {
                if (fabsf(actual_rpm) < STALL_DETECTION_RPM_THRESHOLD) {
                    if (stall_cnt[motor] < 255) stall_cnt[motor]++;
                } else {
                    stall_cnt[motor] = 0;
                }
            } else {
                stall_cnt[motor] = 0;
            }

            if (stall_cnt[motor] >= STALL_DETECTION_CYCLES) {
                stall_latched[motor] = 1;
            }

            if (stall_latched[motor]) {
                PID_Reset(&pid_motor[motor]);
                int16_t creep = (sp >= 0.0f) ? STALL_RECOVERY_CREEP_PWM
                                             : -STALL_RECOVERY_CREEP_PWM;
                Motor_SetSpeed((MotorID_t)motor, creep);

                if (fabsf(actual_rpm) > STALL_RECOVERY_RPM_THRESHOLD) {
                    stall_latched[motor] = 0;
                    stall_cnt[motor]     = 0;
                }
                continue;
            }

            // --- PID + dynamic tuning using ramped setpoint (sp) ---
            PID_SetDynamicTunings(&pid_motor[motor], sp);
            float pwm_output = PID_Compute(&pid_motor[motor], sp, actual_rpm);

            // --- Feedforward still based on sp ---
            if (fabsf(sp) > FEEDFORWARD_MIN_RPM) {
                float ff_gain = 0.0f;
                switch (motor) {
                    case MOTOR_1: ff_gain = MOTOR_FF_GAIN_1; break;
                    case MOTOR_2: ff_gain = MOTOR_FF_GAIN_2; break;
                    case MOTOR_3: ff_gain = MOTOR_FF_GAIN_3; break;
                    case MOTOR_4: ff_gain = MOTOR_FF_GAIN_4; break;
                    default: break;
                }
                pwm_output += ff_gain * sp;
            }

            Motor_SetSpeed((MotorID_t)motor, (int16_t)pwm_output);
        }

        // 🔁 MOVING AVERAGE UPDATE (what you’re missing now)
        for (int motor = MOTOR_1; motor <= MOTOR_4; motor++) {
            float current_rpm = Encoder_GetRPM((MotorID_t)motor);
            rpm_history[motor][rpm_index[motor]] = current_rpm;
            rpm_index[motor] = (rpm_index[motor] + 1) % RPM_AVG_WINDOW;

            float sum = 0.0f;
            for (int i = 0; i < RPM_AVG_WINDOW; i++) {
                sum += rpm_history[motor][i];
            }
            rpm_avg[motor] = sum / RPM_AVG_WINDOW;
        }

        // If we timed out, auto-disarm once and log it
        if (timeout && system_armed) {
            system_armed = 0;
            robot_stop();
            last_cmd_ms = 0;
            LOGE("SAFETY: Command timeout -> DISARMED, all RPM = 0");
        }

        osDelay(PID_SAMPLE_TIME_MS);
    }
}



void TaskSafety(void *argument)
{
    for (;;)
    {

        // ===== CHECK CONTROL LOOP HEALTH FIRST =====
        uint32_t now = HAL_GetTick();
        if (last_control_loop_ms != 0) {  // Only check after first loop
            uint32_t stall_time = now - last_control_loop_ms;

            if (stall_time > 200) {  // Control loop hasn't run in 200ms!
                // EMERGENCY: Force all motors off
                Motor_AllStop();
                HAL_GPIO_WritePin(MOTOR_NSLEEP_PORT, MOTOR_NSLEEP_PIN, GPIO_PIN_RESET);

                // Log critical error
                LOGE("CRITICAL: Control loop stalled for %lu ms! Motors disabled.", stall_time);

                // Wait here for watchdog to reset system (~16 seconds)
                while(1) {
                    osDelay(100);
                }
            }
        }

        osDelay(100);

        for (int motor = MOTOR_1; motor <= MOTOR_4; motor++) {
            if (Motor_CheckFault((MotorID_t)motor)) {

                Motor_AllStop();

                MotorFault_t fault_type = Motor_GetFaultStatus((MotorID_t)motor);
                const char* fault_name;

                switch(fault_type) {
                    case MOTOR_FAULT_OVERCURRENT:  fault_name = "OVERCURRENT";      break;
                    case MOTOR_FAULT_OVERTEMP:     fault_name = "OVERTEMPERATURE";  break;
                    case MOTOR_FAULT_UNDERVOLTAGE: fault_name = "UNDERVOLTAGE";    break;
                    case MOTOR_FAULT_OVERVOLTAGE:  fault_name = "OVERVOLTAGE";     break;
                    default:                        fault_name = "UNKNOWN";         break;
                }

                char fault_msg[200];
                snprintf(fault_msg, sizeof(fault_msg),
                    "!!! MOTOR FAULT DETECTED - ALL STOPPED !!!"
                    "!!! Motor: M%d | Fault Type: %s !!!"
                    "!!! Fault Count: %lu | Timestamp: %lu ms !!!\r\n",
                    motor, fault_name,
                    motor_status[motor].fault_count,
                    motor_status[motor].fault_timestamp);
                LOGI("%s", fault_msg);

                break;
            }
        }
    }
}

void TaskSensor(void *argument)
{
    static bool adc_started = false;

    osDelay(1000);  // wait 1 s after boot for safety
    if (!adc_started) {
        LOGI("Starting ADC DMA...");
        ADC_Utils_Init();
        LOGI("ADC DMA started.");
        adc_started = true;
    }

    for (;;)
    {
        osDelay(10);
        imu_update_timer();
        imu_read_nonblocking(&current_imu_data);
    }
}

void TaskTelemetry(void *argument)
{
    static char buffer[384];  // Increased slightly for extra data
    static uint32_t loop_count = 0;
    static uint32_t tx_errors = 0;

    for (;;)
    {
        osDelay(500);
        loop_count++;

        // In ROS mode, completely skip ASCII telemetry on USB
        if (ros_mode_enabled) {
        	osDelay(500);
            continue;
        }

        // ✅ Rotate between 3 display modes every 3 loops
        uint8_t mode = (loop_count / 3) % 3;
        int pos = 0;

        switch(mode) {
            case 0:  // Mode 0: RPM + Average + Ticks
                pos = snprintf(buffer, sizeof(buffer),
                    "[%lu] M1:%5.1f/%5.1f(%5.1f,%6ld) M2:%5.1f/%5.1f(%5.1f,%6ld) M3:%5.1f/%5.1f(%5.1f,%6ld) M4:%5.1f/%5.1f(%5.1f,%6ld)\r\n",
                    loop_count,
                    Encoder_GetRPM(MOTOR_1), target_rpm[MOTOR_1], rpm_avg[MOTOR_1], (long)Encoder_GetTotalTicks(MOTOR_1),
                    Encoder_GetRPM(MOTOR_2), target_rpm[MOTOR_2], rpm_avg[MOTOR_2], (long)Encoder_GetTotalTicks(MOTOR_2),
                    Encoder_GetRPM(MOTOR_3), target_rpm[MOTOR_3], rpm_avg[MOTOR_3], (long)Encoder_GetTotalTicks(MOTOR_3),
                    Encoder_GetRPM(MOTOR_4), target_rpm[MOTOR_4], rpm_avg[MOTOR_4], (long)Encoder_GetTotalTicks(MOTOR_4));
                break;

            case 1:  // Mode 1: IMU Data
                pos = snprintf(buffer, sizeof(buffer),
                    "[%lu] IMU: Accel[X:%6.2f Y:%6.2f Z:%6.2f] Gyro[X:%6.1f Y:%6.1f Z:%6.1f] (m/s^2, deg/s)\r\n",
                    loop_count,
                    current_imu_data.ax_g, current_imu_data.ay_g, current_imu_data.az_g,
                    current_imu_data.gx_dps, current_imu_data.gy_dps, current_imu_data.gz_dps);
                break;

            case 2:  // Mode 2: Status + Errors + Battery
            {
                uint32_t uptime_sec = HAL_GetTick() / 1000;
                char status_flags[8] = "----";

                for (int m = MOTOR_1; m <= MOTOR_4; m++) {
                    if (motor_status[m].is_faulted)      status_flags[m-1] = 'F';
                    else if (stall_latched[m])           status_flags[m-1] = 'S';
                    else                                 status_flags[m-1] = 'O';
                }

                batt_v = ADC_Utils_GetBatteryVoltage();

                if (tx_errors > 5) {
                    pos = snprintf(buffer, sizeof(buffer),
                        "[%lu] Uptime:%lu:%02lu Batt:%.2fV Status:[%s] USB_Err:%lu⚠ FaultCnt:[%lu,%lu,%lu,%lu]\r\n",
                        loop_count, uptime_sec / 60, uptime_sec % 60,
                        batt_v, status_flags,
                        tx_errors,
                        motor_status[MOTOR_1].fault_count,
                        motor_status[MOTOR_2].fault_count,
                        motor_status[MOTOR_3].fault_count,
                        motor_status[MOTOR_4].fault_count);
                } else {
                    pos = snprintf(buffer, sizeof(buffer),
                        "[%lu] Uptime:%lu:%02lu Batt:%.2fV Status:[%s] FaultCnt:[%lu,%lu,%lu,%lu]\r\n",
                        loop_count, uptime_sec / 60, uptime_sec % 60,
                        batt_v, status_flags,
                        motor_status[MOTOR_1].fault_count,
                        motor_status[MOTOR_2].fault_count,
                        motor_status[MOTOR_3].fault_count,
                        motor_status[MOTOR_4].fault_count);
                }
                break;
            }
        }

        // Update OLED
        int batt_pct = 0;
        if (batt_v > 10.0f) {
            batt_pct = (int)((batt_v - 9.3f) / 2.6f * 100.0f);  // 9.3V=0%, 12.6V=100%
            if (batt_pct > 100) batt_pct = 100;
        }

        oled_set_battery(batt_v, batt_pct);
        oled_set_ros_status(ros_mode_enabled);
        oled_set_mode(system_armed ? "ARMED" : "IDLE");
        oled_app_update();

        // ✅ Single atomic transmission with error tracking
        if (pos > 0 && pos < sizeof(buffer)) {
            uint8_t result = USB_Send((uint8_t*)buffer, pos);
            if (result != USBD_OK) {
                tx_errors++;
            }
            osDelay(30);  // Wait for USB flush
        }
    }
}


void TaskTransportRX(void *argument)
{
    char line[USB_CMD_MAX_LEN];

    for (;;)
    {
        if (transport_usb_get_line(line, sizeof(line))) {

            // Optional: mark USB as active transport
            // update_transport_activity(TRANSPORT_USB);

            // Debug echo
            char dbg[96];
            snprintf(dbg, sizeof(dbg), "RX_CMD: '%s'\r\n", line);
            LOGI("%s", dbg);

            // Normalize to uppercase for command word
            // Trim leading/trailing whitespace first
            // (useful if transport_usb_get_line returned something with leading space)
            char *start = line;
            while (*start == ' ' || *start == '\t') start++;

            // Find first separator (space or tab)
            char *sep = strpbrk(start, " \t");

            // If we found a separator, split the string in-place: cmd -> [start], args -> first non-space after sep
            char *cmd = NULL;
            char *args = NULL;

            if (sep) {
                *sep = '\0';          // terminate command
                cmd = start;

                // args start after sep; skip any additional spaces/tabs
                args = sep + 1;
                while (*args == ' ' || *args == '\t') args++;

                // If args is empty string, treat as NULL
                if (*args == '\0') args = NULL;
            } else {
                // No separator → entire line is the command, no args
                cmd = start;
                args = NULL;
            }

            // Normalize command to uppercase (only the command portion)
            for (char *p = cmd; *p; p++) {
                if (*p >= 'a' && *p <= 'z') *p = *p - 'a' + 'A';
            }


            if (!cmd) {
                osDelay(5);
                continue;
            }

            // ===== CORE MOTION COMMANDS =====
            if (strcmp(cmd, "ARM") == 0) {
                lyra_cmd_arm();
            }
            else if (strcmp(cmd, "DISARM") == 0) {
                lyra_cmd_disarm();
            }
            else if (strcmp(cmd, "STOP") == 0) {
                lyra_cmd_stop();
            }
            else if (strcmp(cmd, "ALL") == 0) {
                float rpm = 0.0f;
                if (args) rpm = atof(args);
                lyra_cmd_set_all_rpm(rpm);
            }
            else if (strcmp(cmd, "SKID") == 0) {
                float v = 0.0f, w = 0.0f;
                if (args) sscanf(args, "%f %f", &v, &w);
                lyra_cmd_set_skid(v, w);
            }
            else if (strcmp(cmd, "SET_WHEEL_VEL") == 0) {
                // ASCII test hook for binary-style wheel command
                float w1, w2, w3, w4;
                if (!args || sscanf(args, "%f %f %f %f", &w1, &w2, &w3, &w4) != 4) {
                    LOGE("ERR: use SET_WHEEL_VEL w1 w2 w3 w4 (rad/s)");
                } else {
                    float w[4] = { w1, w2, w3, w4 };
                    lyra_cmd_set_wheel_vel_rad_s(w);
                }
            }

            // ===== ROS MODE / CONFIG MANAGEMENT =====
            else if (strcmp(cmd, "SET_ROS_MODE") == 0) {
                int enable = 0;
                if (args) {
                    enable = atoi(args);
                }
                lyra_cmd_set_ros_mode(enable ? 1 : 0);
            }
            else if (strcmp(cmd, "SAVE_CONFIG") == 0) {
                config_request_save();
            }
            else if (strcmp(cmd, "LOAD_CONFIG") == 0) {
                config_init();
                config_print();
            }

            // ===== PID TUNING (TEXT) =====
            else if (strcmp(cmd, "GET_PID") == 0) {
                int m = 0;
                if (args) m = atoi(args);

                if (m >= 1 && m <= 4) {
                    LOGI("PID: M%d -> Kp=%.3f Ki=%.3f Kd=%.3f",
                         m,
                         g_config.kp[m-1],
                         g_config.ki[m-1],
                         g_config.kd[m-1]);
                } else {
                    LOGI("PID: ALL ->");
                    for (int i = 0; i < 4; i++) {
                        LOGI(" M%d: Kp=%.3f Ki=%.3f Kd=%.3f",
                             i + 1,
                             g_config.kp[i],
                             g_config.ki[i],
                             g_config.kd[i]);
                    }
                }
            }

            else if (strcmp(cmd, "SET_PID") == 0) {
                int   m;
                float kp, ki, kd;
                if (!args || sscanf(args, "%d %f %f %f", &m, &kp, &ki, &kd) != 4) {
                    LOGE("ERR: use SET_PID <motor 1-4> <Kp> <Ki> <Kd>");
                } else {
                    lyra_cmd_set_pid((uint8_t)m, kp, ki, kd);
                }
            }

            else if (strcmp(cmd, "RESET_PID") == 0) {
                for (int i = 0; i < 4; i++) {
                    g_config.kp[i] = PID_KP_DEFAULT;
                    g_config.ki[i] = PID_KI_DEFAULT;
                    g_config.kd[i] = PID_KD_DEFAULT;

                    PID_Init(&pid_motor[i+1],
                             PID_KP_DEFAULT,
                             PID_KI_DEFAULT,
                             PID_KD_DEFAULT,
                             PID_OUTPUT_LIMIT);
                }
                LOGI("PID: Reset to defaults -> Kp=%.3f Ki=%.3f Kd=%.3f", PID_KP_DEFAULT, PID_KI_DEFAULT, PID_KD_DEFAULT);
            }

            else if (strcmp(cmd, "GET_IBUS") == 0) {
                if (!ibus_state.valid) {
                    LOGW("IBUS: no valid frame received yet, rx_bytes=%lu", ibus_rx_byte_count);
                } else {
                    uint32_t age = HAL_GetTick() - ibus_state.last_update_ms;

                    const config_t* cfg = config_get();
                    LOGI("IBUS: chT=%.2f chS=%.2f chA=%.2f age=%lums rx_bytes=%lu",
                         ibus_state.ch[cfg->rc_ch_throttle],
                         ibus_state.ch[cfg->rc_ch_steering],
                         ibus_state.ch[cfg->rc_ch_arm],
                         age,
                         ibus_rx_byte_count);
                }
            }

            else if (strcmp(cmd, "GET_IBUSRAW") == 0) {
                // Dump the last 32 raw bytes seen on UART5 (iBus line)
                char buf[160];
                int pos = 0;

                // Start from the oldest of the last 32 bytes
                const int n = 32;
                uint8_t idx = ibus_raw_index;

                // Compute start index in the ring buffer
                uint8_t start = (idx + IBUS_RAW_BUF_SIZE - n) % IBUS_RAW_BUF_SIZE;

                pos += snprintf(buf + pos, sizeof(buf) - pos, "IBUSRAW:");

                for (int i = 0; i < n && pos < (int)(sizeof(buf) - 4); i++) {
                    uint8_t b = ibus_raw_buf[(start + i) % IBUS_RAW_BUF_SIZE];
                    pos += snprintf(buf + pos, sizeof(buf) - pos, " %02X", b);
                }

                LOGI("%s", buf);
            }

            // ===== TRANSPORT CONFIGURATION =====
            else if (strcmp(cmd, "SET_DEFAULT_TRANSPORT") == 0) {

                if (!args) {
                    LOGE("ERR: use SET_DEFAULT_TRANSPORT <0=USB|1=UART3|2=BOTH>");
                    osDelay(5);
                    continue;
                }

                // Trim leading spaces
                while (*args == ' ' || *args == '\t') args++;

                // Use strtol with error checking
                char *endptr = NULL;
                long val = strtol(args, &endptr, 10);

                // Trim trailing spaces
                while (endptr && (*endptr == ' ' || *endptr == '\t')) endptr++;

                // Validate parse success
                if (endptr == args || val < 0 || val > 2) {
                    LOGE("ERR: use SET_DEFAULT_TRANSPORT <0=USB|1=UART3|2=BOTH>");
                    osDelay(5);
                    continue;
                }

                int transport = (int)val;

                // Debug: show numeric transport value we parsed
                LOGI("DEBUG: parsed transport = %d", transport);

                // Set config + runtime target
                g_config.default_transport = (uint8_t)transport;
                g_transport_target = (TransportTarget_t)transport;

                // Confirm after assign
                LOGI("DEBUG: g_config.default_transport=%u g_transport_target=%u",
                     (unsigned)g_config.default_transport,
                     (unsigned)g_transport_target);

                // Friendly user message
                const char *names[] = {"USB", "UART3", "BOTH"};
                char msg[128];
                int len = snprintf(msg, sizeof(msg),
                                  "[I] %8lu CONFIG: Default transport = %s (will save to flash)\r\n",
                                  HAL_GetTick(), names[transport]);
                USB_Send((uint8_t*)msg, len);
                osDelay(100);

                config_request_save();
            }

            else if (strcmp(cmd, "GET_TRANSPORT") == 0) {
                const char *names[] = {"USB", "UART3", "BOTH"};
                LOGI("Transport: Current=%s, Default=%s",
                     names[g_transport_target],
                     names[g_config.default_transport]);
            }

            else if (strcmp(cmd, "FACTORY_RESET") == 0) {
                config_reset_to_defaults();
                config_request_save();
                LOGI("CONFIG: Factory defaults restored and saved");
            }

            // ===== UNKNOWN =====
            else {
                LOGW("WARN: Unknown cmd");
            }
        }

        osDelay(5);
    }
}


void TaskRC(void *argument)
{
    for(;;) {
        ibus_task_update();
        osDelay(20);   // 50Hz
    }
}

void TaskTransportRX_UART(void *argument)
{
    char line[USB_CMD_MAX_LEN];
    for (;;)
    {
        if (transport_uart_get_line(line, sizeof(line))) {
            // mirror logic from USB Task
            char dbg[96];
            snprintf(dbg, sizeof(dbg), "[UART3_CMD] '%s'\r\n", line);
            LOGI("%s", dbg);
            // optionally handle ASCII commands if needed
        }
        osDelay(5);
    }
}


// ===== RTOS INIT ENTRYPOINT =====
void app_rtos_init(void)
{
    // Initialize telemetry transport (MUST be after kernel init)
    lyra_proto_init_tx();

    const osThreadAttr_t motorTask_attributes = {
        .name       = "TaskMotorControl",
        .stack_size = 512 * 4,
        .priority   = (osPriority_t) osPriorityHigh5,
    };

    const osThreadAttr_t safetyTask_attributes = {
        .name       = "TaskSafety",
        .stack_size = 256 * 4,
        .priority   = (osPriority_t) osPriorityHigh5,
    };

    const osThreadAttr_t transportTask_attributes = {
        .name       = "TaskTransportRX",
        .stack_size = 512 * 4,
        .priority   = (osPriority_t) osPriorityHigh4,
    };

    const osThreadAttr_t telemetryTask_attributes = {
        .name       = "TaskTelemetry",
        .stack_size = 256 * 4,
        .priority   = (osPriority_t) osPriorityHigh3,
    };

    const osThreadAttr_t sensorTask_attributes = {
        .name       = "TaskSensor",
        .stack_size = 256 * 4,
        .priority   = (osPriority_t) osPriorityHigh2,
    };

    const osThreadAttr_t rcTask_attributes = {
        .name = "TaskRC",
        .stack_size = 256 * 4,
        .priority = (osPriority_t) osPriorityHigh3,
    };

    const osThreadAttr_t configTask_attributes = {
        .name = "TaskConfigWrite",
        .stack_size = 256 * 4,
        .priority = (osPriority_t) osPriorityBelowNormal,  // lowest priority
    };

    const osThreadAttr_t uartTransportTask_attributes = {
        .name       = "TaskTransportRX_UART",
        .stack_size = 512 * 4,
        .priority   = (osPriority_t) osPriorityHigh4,
    };

    osThreadNew(TaskMotorControl, NULL, &motorTask_attributes);
    osThreadNew(TaskSafety,       NULL, &safetyTask_attributes);
    osThreadNew(TaskTransportRX,  NULL, &transportTask_attributes);
    osThreadNew(TaskTelemetry,    NULL, &telemetryTask_attributes);
    osThreadNew(TaskSensor,       NULL, &sensorTask_attributes);
    osThreadNew(TaskRC, 		  NULL, &rcTask_attributes);
    osThreadNew(TaskConfigWrite,  NULL, &configTask_attributes);
    osThreadNew(TaskTransportRX_UART, NULL, &uartTransportTask_attributes);
}
