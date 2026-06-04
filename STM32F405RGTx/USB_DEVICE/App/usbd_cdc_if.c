/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : usbd_cdc_if.c
  * @version        : v2.4_FIXED
  * @brief          : Usb device for Virtual Com Port - WITH RACE CONDITION FIXES
  ******************************************************************************
  */
/* USER CODE END Header */

/* Includes ------------------------------------------------------------------*/
#include "usbd_cdc_if.h"

/* USER CODE BEGIN INCLUDE */
#include "app/app_transport.h"
#include "cmsis_os2.h"
/* USER CODE END INCLUDE */

/* Private typedef -----------------------------------------------------------*/
/* Private define ------------------------------------------------------------*/
/* Private macro -------------------------------------------------------------*/

/* USER CODE BEGIN PV */
// RTOS_MUTEX
static osMutexId_t usb_tx_mutex = NULL;
static const osMutexAttr_t usb_tx_mutex_attr = {
    .name = "usb_tx_mutex"
};

/* Private variables ---------------------------------------------------------*/
static volatile uint8_t usb_cdc_ready = 0;
/* USER CODE END PV */

/** @addtogroup STM32_USB_OTG_DEVICE_LIBRARY
  * @brief Usb device library.
  * @{
  */

/** @addtogroup USBD_CDC_IF
  * @{
  */

/** @defgroup USBD_CDC_IF_Private_TypesDefinitions USBD_CDC_IF_Private_TypesDefinitions
  * @brief Private types.
  * @{
  */

/* USER CODE BEGIN PRIVATE_TYPES */

/* USER CODE END PRIVATE_TYPES */

/**
  * @}
  */

/** @defgroup USBD_CDC_IF_Private_Defines USBD_CDC_IF_Private_Defines
  * @brief Private defines.
  * @{
  */

/* USER CODE BEGIN PRIVATE_DEFINES */
/* USER CODE END PRIVATE_DEFINES */

/**
  * @}
  */

/** @defgroup USBD_CDC_IF_Private_Macros USBD_CDC_IF_Private_Macros
  * @brief Private macros.
  * @{
  */

/* USER CODE BEGIN PRIVATE_MACRO */

/* USER CODE END PRIVATE_MACRO */

/**
  * @}
  */

/** @defgroup USBD_CDC_IF_Private_Variables USBD_CDC_IF_Private_Variables
  * @brief Private variables.
  * @{
  */
/* Create buffer for reception and transmission           */
/* It's up to user to redefine and/or remove those define */
/** Received data over USB are stored in this buffer      */
uint8_t UserRxBufferFS[APP_RX_DATA_SIZE];

/** Data to send over USB CDC are stored in this buffer   */
uint8_t UserTxBufferFS[APP_TX_DATA_SIZE];

/* USER CODE BEGIN PRIVATE_VARIABLES */
#define CDC_TX_QUEUE_SIZE 1024
#define CDC_TX_QUEUE_MASK (CDC_TX_QUEUE_SIZE - 1)
static uint8_t cdc_tx_ringbuf[CDC_TX_QUEUE_SIZE];
static volatile uint16_t cdc_tx_head = 0;
static volatile uint16_t cdc_tx_tail = 0;
static volatile uint8_t cdc_tx_busy = 0;
/* USER CODE END PRIVATE_VARIABLES */

/**
  * @}
  */

/** @defgroup USBD_CDC_IF_Exported_Variables USBD_CDC_IF_Exported_Variables
  * @brief Public variables.
  * @{
  */

extern USBD_HandleTypeDef hUsbDeviceFS;

/* USER CODE BEGIN EXPORTED_VARIABLES */

/* USER CODE END EXPORTED_VARIABLES */

/**
  * @}
  */

/** @defgroup USBD_CDC_IF_Private_FunctionPrototypes USBD_CDC_IF_Private_FunctionPrototypes
  * @brief Private functions declaration.
  * @{
  */

static int8_t CDC_Init_FS(void);
static int8_t CDC_DeInit_FS(void);
static int8_t CDC_Control_FS(uint8_t cmd, uint8_t* pbuf, uint16_t length);
static int8_t CDC_Receive_FS(uint8_t* pbuf, uint32_t *Len);
static int8_t CDC_TransmitCplt_FS(uint8_t *pbuf, uint32_t *Len, uint8_t epnum);

/* USER CODE BEGIN PRIVATE_FUNCTIONS_DECLARATION */

/* USER CODE END PRIVATE_FUNCTIONS_DECLARATION */

/**
  * @}
  */

USBD_CDC_ItfTypeDef USBD_Interface_fops_FS =
{
  CDC_Init_FS,
  CDC_DeInit_FS,
  CDC_Control_FS,
  CDC_Receive_FS,
  CDC_TransmitCplt_FS
};

/* Private functions ---------------------------------------------------------*/
/**
  * @brief  Initializes the CDC media low layer over the FS USB IP
  * @retval USBD_OK if all operations are OK else USBD_FAIL
  */
static int8_t CDC_Init_FS(void)
{
  /* USER CODE BEGIN 3 */
  /* Set Application Buffers */
  USBD_CDC_SetTxBuffer(&hUsbDeviceFS, UserTxBufferFS, 0);
  USBD_CDC_SetRxBuffer(&hUsbDeviceFS, UserRxBufferFS);
  USBD_CDC_ReceivePacket(&hUsbDeviceFS);

  // ✅ FIX: Create mutex BEFORE setting ready flag
  if (usb_tx_mutex == NULL) {
      usb_tx_mutex = osMutexNew(&usb_tx_mutex_attr);
  }

  usb_cdc_ready = 1;

  return (USBD_OK);
  /* USER CODE END 3 */
}

/**
  * @brief  DeInitializes the CDC media low layer
  * @retval USBD_OK if all operations are OK else USBD_FAIL
  */
static int8_t CDC_DeInit_FS(void)
{
  /* USER CODE BEGIN 4 */
  usb_cdc_ready = 0;
  return (USBD_OK);
  /* USER CODE END 4 */
}

/**
  * @brief  Manage the CDC class requests
  * @param  cmd: Command code
  * @param  pbuf: Buffer containing command data (request parameters)
  * @param  length: Number of data to be sent (in bytes)
  * @retval Result of the operation: USBD_OK if all operations are OK else USBD_FAIL
  */
static int8_t CDC_Control_FS(uint8_t cmd, uint8_t* pbuf, uint16_t length)
{
  /* USER CODE BEGIN 5 */
  switch(cmd)
  {
    case CDC_SEND_ENCAPSULATED_COMMAND:
    break;

    case CDC_GET_ENCAPSULATED_RESPONSE:
    break;

    case CDC_SET_COMM_FEATURE:
    break;

    case CDC_GET_COMM_FEATURE:
    break;

    case CDC_CLEAR_COMM_FEATURE:
    break;

  /*******************************************************************************/
  /* Line Coding Structure                                                       */
  /*-----------------------------------------------------------------------------*/
  /* Offset | Field       | Size | Value  | Description                          */
  /* 0      | dwDTERate   |   4  | Number |Data terminal rate, in bits per second*/
  /* 4      | bCharFormat |   1  | Number | Stop bits                            */
  /*                                        0 - 1 Stop bit                       */
  /*                                        1 - 1.5 Stop bits                    */
  /*                                        2 - 2 Stop bits                      */
  /* 5      | bParityType |  1   | Number | Parity                               */
  /*                                        0 - None                             */
  /*                                        1 - Odd                              */
  /*                                        2 - Even                             */
  /*                                        3 - Mark                             */
  /*                                        4 - Space                            */
  /* 6      | bDataBits  |   1   | Number Data bits (5, 6, 7, 8 or 16).          */
  /*******************************************************************************/
    case CDC_SET_LINE_CODING:
    break;

    case CDC_GET_LINE_CODING:
    break;

    case CDC_SET_CONTROL_LINE_STATE:
    break;

    case CDC_SEND_BREAK:
    break;

  default:
    break;
  }

  return (USBD_OK);
  /* USER CODE END 5 */
}

/**
  * @brief  Data received over USB OUT endpoint are sent over CDC interface
  *         through this function.
  *
  *         @note
  *         This function will issue a NAK packet on any OUT packet received on
  *         USB endpoint until exiting this function. If you exit this function
  *         before transfer is complete on CDC interface (ie. using DMA controller)
  *         it will result in receiving more data while previous ones are still
  *         not sent.
  *
  * @param  Buf: Buffer of data to be received
  * @param  Len: Number of data received (in bytes)
  * @retval Result of the operation: USBD_OK if all operations are OK else USBD_FAIL
  */
static int8_t CDC_Receive_FS(uint8_t* Buf, uint32_t *Len)
{
  /* USER CODE BEGIN 6 */
  // Feed received bytes into our transport layer
  transport_usb_on_rx(Buf, *Len);
  // Re-arm USB RX for next packet
  USBD_CDC_SetRxBuffer(&hUsbDeviceFS, &UserRxBufferFS[0]);
  USBD_CDC_ReceivePacket(&hUsbDeviceFS);
  return (USBD_OK);
  /* USER CODE END 6 */
}

/**
  * @brief  CDC_Transmit_FS
  *         Data to send over USB IN endpoint are sent over CDC interface
  *         through this function.
  *         @note
  *
  *
  * @param  Buf: Buffer of data to be sent
  * @param  Len: Number of data to be sent (in bytes)
  * @retval USBD_OK if all operations are OK else USBD_FAIL or USBD_BUSY
  */
uint8_t CDC_Transmit_FS(uint8_t* Buf, uint16_t Len)
{
  uint8_t result = USBD_OK;
  /* USER CODE BEGIN 7 */
  USBD_CDC_HandleTypeDef *hcdc = (USBD_CDC_HandleTypeDef*)hUsbDeviceFS.pClassData;
  if (hcdc->TxState != 0){
    return USBD_BUSY;
  }
  USBD_CDC_SetTxBuffer(&hUsbDeviceFS, Buf, Len);
  result = USBD_CDC_TransmitPacket(&hUsbDeviceFS);
  /* USER CODE END 7 */
  return result;
}

/**
  * @brief  CDC_TransmitCplt_FS
  *         Data transmitted callback
  *
  *         @note
  *         This function is IN transfer complete callback used to inform user that
  *         the submitted Data is successfully sent over USB.
  *
  * @param  Buf: Buffer of data to be received
  * @param  Len: Number of data received (in bytes)
  * @retval Result of the operation: USBD_OK if all operations are OK else USBD_FAIL
  */
static int8_t CDC_TransmitCplt_FS(uint8_t *Buf, uint32_t *Len, uint8_t epnum)
{
  uint8_t result = USBD_OK;
  /* USER CODE BEGIN 13 */

  /* ✅ FIX: Single critical section with IRQs disabled until transmission starts */
  __disable_irq();

  cdc_tx_busy = 0;
  __DMB();  // Memory barrier

  /* If buffer empty, nothing to transmit */
  if (cdc_tx_tail == cdc_tx_head) {
      __enable_irq();
      return result;
  }

  /* Build next chunk while IRQs disabled */
  uint16_t chunk_len = 0;
  uint16_t idx = 0;

  // ✅ FIX: Use fast bitwise mask instead of modulo
  while (cdc_tx_tail != cdc_tx_head && chunk_len < APP_TX_DATA_SIZE) {
      UserTxBufferFS[idx++] = cdc_tx_ringbuf[cdc_tx_tail];
      cdc_tx_tail = (cdc_tx_tail + 1) & CDC_TX_QUEUE_MASK;  // ✅ Fast!
      chunk_len++;
  }

  /* Mark busy BEFORE starting transmission */
  cdc_tx_busy = (chunk_len > 0) ? 1 : 0;
  __DMB();  // Memory barrier

  if (chunk_len > 0) {
      /* Set buffer and start transmission while IRQs still disabled */
      USBD_CDC_SetTxBuffer(&hUsbDeviceFS, UserTxBufferFS, chunk_len);
      uint8_t tx_result = USBD_CDC_TransmitPacket(&hUsbDeviceFS);

      // Enable IRQs AFTER transmission started (prevents re-entrancy)
      __enable_irq();

      if (tx_result != USBD_OK) {
          /* Rollback on failure */
          __disable_irq();
          cdc_tx_tail = (cdc_tx_tail + CDC_TX_QUEUE_SIZE - chunk_len) & CDC_TX_QUEUE_MASK;
          cdc_tx_busy = 0;
          __DMB();
          __enable_irq();
      }
  } else {
      __enable_irq();
  }

  /* USER CODE END 13 */
  return result;
}

/* USER CODE BEGIN PRIVATE_FUNCTIONS_IMPLEMENTATION */
uint8_t USB_CDC_IsReady(void)
{
    return (usb_cdc_ready != 0 && hUsbDeviceFS.pClassData != NULL);
}

uint8_t USB_Send(const uint8_t *buf, uint16_t len)
{
    if (!buf || len == 0) return USBD_FAIL;
    if (!USB_CDC_IsReady()) return USBD_FAIL;

    /* Mutex for task-to-task protection (producers) */
    if (osKernelGetState() == osKernelRunning && usb_tx_mutex) {
        if (osMutexAcquire(usb_tx_mutex, osWaitForever) != osOK) {
            return USBD_FAIL;
        }
    }

    /* Quick capacity check under short critical section */
    __disable_irq();
    uint16_t head = cdc_tx_head;
    uint16_t tail = cdc_tx_tail;
    uint16_t free_space;
    if (tail <= head) free_space = (CDC_TX_QUEUE_SIZE - 1) - (head - tail);
    else free_space = (tail - head - 1);
    __enable_irq();

    if (len > free_space) {
        /* not enough space - fail fast */
        if (osKernelGetState() == osKernelRunning && usb_tx_mutex) osMutexRelease(usb_tx_mutex);
        return USBD_FAIL;
    }

    /* ✅ FIX: Batch write to ring buffer, then atomic head update */
    uint16_t local_head = cdc_tx_head;
    for (uint16_t i = 0; i < len; ++i) {
        cdc_tx_ringbuf[local_head] = buf[i];
        local_head = (local_head + 1) & CDC_TX_QUEUE_MASK;  // ✅ Fast mask
    }

    // ✅ Single atomic update of head
    __disable_irq();
    cdc_tx_head = local_head;
    __DMB();
    __enable_irq();

    /* If USB idle, build a chunk and start TX */
    __disable_irq();
    uint8_t need_start = (!cdc_tx_busy && (cdc_tx_tail != cdc_tx_head));
    __enable_irq();

    if (need_start) {
        uint16_t chunk_len = 0;
        uint16_t idx = 0;

        /* Pull chunk and advance tail under IRQ disabled */
        __disable_irq();
        while (cdc_tx_tail != cdc_tx_head && chunk_len < APP_TX_DATA_SIZE) {
            UserTxBufferFS[idx++] = cdc_tx_ringbuf[cdc_tx_tail];
            cdc_tx_tail = (cdc_tx_tail + 1) & CDC_TX_QUEUE_MASK;  // ✅ Fast mask
            chunk_len++;
        }
        /* mark busy while still disabled to avoid races */
        cdc_tx_busy = (chunk_len > 0) ? 1 : 0;
        __DMB();

        if (chunk_len > 0) {
            USBD_CDC_SetTxBuffer(&hUsbDeviceFS, UserTxBufferFS, chunk_len);
            uint8_t tx_result = USBD_CDC_TransmitPacket(&hUsbDeviceFS);

            // ✅ Enable IRQs AFTER starting transmission
            __enable_irq();

            if (tx_result != USBD_OK) {
                /* rollback tail and clear busy under IRQ disabled */
                __disable_irq();
                cdc_tx_tail = (cdc_tx_tail + CDC_TX_QUEUE_SIZE - chunk_len) & CDC_TX_QUEUE_MASK;
                cdc_tx_busy = 0;
                __DMB();
                __enable_irq();

                if (osKernelGetState() == osKernelRunning && usb_tx_mutex) osMutexRelease(usb_tx_mutex);
                return USBD_FAIL;
            }
        } else {
            __enable_irq();
        }
    }

    if (osKernelGetState() == osKernelRunning && usb_tx_mutex) {
        osMutexRelease(usb_tx_mutex);
    }
    return USBD_OK;
}

/* USER CODE END PRIVATE_FUNCTIONS_IMPLEMENTATION */

/**
  * @}
  */

/**
  * @}
  */
