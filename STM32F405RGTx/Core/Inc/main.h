/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.h
  * @brief          : Header for main.c file.
  *                   This file contains the common defines of the application.
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2025 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */

/* Define to prevent recursive inclusion -------------------------------------*/
#ifndef __MAIN_H
#define __MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

/* Includes ------------------------------------------------------------------*/
#include "stm32f4xx_hal.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */

/* USER CODE END Includes */

/* Exported types ------------------------------------------------------------*/
/* USER CODE BEGIN ET */

/* USER CODE END ET */

/* Exported constants --------------------------------------------------------*/
/* USER CODE BEGIN EC */

/* USER CODE END EC */

/* Exported macro ------------------------------------------------------------*/
/* USER CODE BEGIN EM */

/* USER CODE END EM */

/* Exported functions prototypes ---------------------------------------------*/
void Error_Handler(void);

/* USER CODE BEGIN EFP */

/* USER CODE END EFP */

/* Private defines -----------------------------------------------------------*/
#define WAKE_UP_Pin GPIO_PIN_13
#define WAKE_UP_GPIO_Port GPIOC
#define FAULT_M3_PIN_Pin GPIO_PIN_4
#define FAULT_M3_PIN_GPIO_Port GPIOC
#define FAULT_M4_PIN_Pin GPIO_PIN_5
#define FAULT_M4_PIN_GPIO_Port GPIOC
#define FAULT_M1_PIN_Pin GPIO_PIN_0
#define FAULT_M1_PIN_GPIO_Port GPIOB
#define FAULT_M2_PIN_Pin GPIO_PIN_1
#define FAULT_M2_PIN_GPIO_Port GPIOB
#define MPU_INTERRUPT_Pin GPIO_PIN_10
#define MPU_INTERRUPT_GPIO_Port GPIOA
#define WS2812B_LED_Pin GPIO_PIN_15
#define WS2812B_LED_GPIO_Port GPIOA
#define nSLEEP_PIN_Pin GPIO_PIN_3
#define nSLEEP_PIN_GPIO_Port GPIOB

/* USER CODE BEGIN Private defines */

/* USER CODE END Private defines */

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */
