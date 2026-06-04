/**
 * File: config_reader.cpp
 * Module: V2X Protocol — Configuration Reader
 *
 * Purpose:
 *    Parses JSON configuration files for OBU and RSU entities.\n *    Provides access to network parameters, crypto settings, and identity.\n *
 * Author(s): Praveen Kumar
 * Company: Siliris Technologies Pvt. Ltd
 * Created: 15th February 2026
 * Version: 1.1
 *
 * Configuration Parameters:\n *    - entity_id: Unique identifier (OBU1, RSU, etc.)\n *    - desktop_ip/port: Registration server location\n *    - rsu_ip/port: (OBU only) RSU connection details\n *    - crypto_provider: Crypto implementation to use\n *    - listen_port: (RSU only) UDP listen port\n *
 * License:
 *    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
 *    Proprietary - See LICENSE file for terms and conditions.
 */

#include "config_reader.h"
namespace v2x {}
