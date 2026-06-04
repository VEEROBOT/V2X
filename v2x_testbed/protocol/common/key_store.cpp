/**
 * File: key_store.cpp
 * Module: V2X Protocol — Key Store
 *
 * Purpose:
 *    Secure local storage and management of cryptographic key material.\n *    Persists keys to disk, loads on startup, provides access to keys\n *    during authentication operations.
 *
 * Author(s): Praveen Kumar
 * Company: Siliris Technologies Pvt. Ltd
 * Created: 15th February 2026
 * Version: 1.1
 *
 * Stores:
 *    - Registration ID (RID)\n *    - Authentication ID (AID)\n *    - Device Auth ID (DAID)\n *    - Private key (SK)\n *    - Own public key (PK_self)\n *    - Peer public keys (PK_peer)\n *
 * License:
 *    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
 *    Proprietary - See LICENSE file for terms and conditions.
 */

#include "key_store.h"
namespace v2x {}
