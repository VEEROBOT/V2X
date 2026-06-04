/**
 * File: receive_buffer.cpp
 * Module: V2X Authentication Testbed — RSU Receive Buffer
 *
 * Purpose:
 *    Buffers incoming UDP packets and prevents packet fragmentation issues.\n *    Stores complete packets until they can be processed by the packet processor.
 *
 * Author(s): Praveen Kumar
 * Company: Siliris Technologies Pvt. Ltd
 * Created: 15th February 2026
 * Version: 1.1
 *
 * Key Responsibilities:
 *    - Accumulate received data
 *    - Validate packet boundaries
 *    - Extract complete messages for processing
 *    - Handle partial/fragmented datagrams
 *
 * License:
 *    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
 *    Proprietary - See LICENSE file for terms and conditions.
 */

#include "receive_buffer.h"
namespace v2x {}
