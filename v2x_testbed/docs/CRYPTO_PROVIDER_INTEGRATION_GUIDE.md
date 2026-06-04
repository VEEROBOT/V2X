
# CRYPTO PROVIDER INTEGRATION GUIDE

**V2X Authentication Testbed – Crypto Abstraction Layer**

---

## 1. Purpose of This Document

This document explains how to integrate a custom cryptographic algorithm into the V2X Authentication Testbed without modifying the authentication protocol, packet formats, or system architecture.

The system has been designed with a strict cryptographic abstraction boundary.
Your implementation must plug into this boundary.

If implemented correctly, no changes are required in:

* RSU server
* OBU client
* Packet serializer
* Session manager
* Desktop server
* Authentication state machine

Only the crypto provider layer is modified.

---

## 2. Architecture Overview

The V2X system is layered as follows:

```
Application Layer (RSU / OBU / Desktop)
        ↓
Protocol Engine (State Machines, Packets)
        ↓
CryptoProvider Interface  ← YOU IMPLEMENT HERE
        ↓
Your Cryptographic Algorithm (NTL / PQC / Custom)
```

Everything above `CryptoProvider` is algorithm-agnostic.

Your implementation must conform exactly to the interface defined in:

```
protocol/crypto/crypto_provider.h
```

---

## 3. Files You Must Modify

You should only modify or extend:

```
protocol/crypto/lattice_provider.h
protocol/crypto/lattice_provider.cpp
```

Do NOT modify:

```
protocol/packets/
protocol/common/
rsu/
obu/
desktop/
```

If you believe changes are required outside the crypto layer, contact the system architect before proceeding.

---

## 4. The CryptoProvider Interface Contract

The abstract interface defines all required operations.

You must implement:

### 4.1 Key Generation

```cpp
generate_keypair()
generate_partial_private_key()
generate_hash_key()
```

Requirements:

* Deterministic output sizes
* No memory leaks
* No global static state
* Return raw byte arrays (not hex, not Base64)

---

### 4.2 KEM Operations

```cpp
encapsulate(recipient_pk)
decapsulate(ct, own_sk)
```

Requirements:

* Shared secret must be exactly 32 bytes
* Deterministic success/failure behavior
* Decapsulation must reject invalid ciphertext cleanly
* No crashes on malformed input

---

### 4.3 Signature Operations

```cpp
sign(message, own_sk)
verify_signature(signature, message, sender_pk)
```

Requirements:

* Verify must return `false` for invalid signatures
* No exceptions thrown for malformed input
* Signature size must match `get_signature_size()`

---

### 4.4 Session Key Derivation

```cpp
derive_master_session_key(ss, nonce_obu, nonce_rsu, session_id)
split_session_key(master_key)
compute_hmac(key, data)
compute_hash(data)
```

Requirements:

* `derive_master_session_key` must return exactly 64 bytes
* `split_session_key` splits into:

  * First 32 bytes → encryption key
  * Next 32 bytes → MAC key
* Hash output must be 32 bytes
* HMAC output must be 32 bytes

---

### 4.5 Authenticated Encryption (Post-Auth Messaging)

```cpp
aes_gcm_encrypt(key, plaintext)
aes_gcm_decrypt(key, ciphertext_with_tag)
```

Requirements:

* Key must be exactly 32 bytes (AES-256)
* `aes_gcm_encrypt` returns: `[12B random nonce] [ciphertext] [16B GCM tag]`
* `aes_gcm_decrypt` input: same format as encrypt output
* Decrypt must throw `std::runtime_error` on authentication failure (tampered data or wrong key)
* Nonce must be randomly generated (12 bytes) for each encryption — never reuse
* Note: This can typically reuse OpenSSL's AES-GCM regardless of the signature/KEM algorithm

---

### 4.6 Provider Identity

```cpp
get_provider_name()
```

Requirements:

* Return a unique string identifying your provider (e.g., `"lattice-ntl"`)
* Used in dashboard metrics and logging

---

## 5. Size Accessor Methods (CRITICAL)

These functions are used by the packet serializer:

```cpp
get_public_key_size()
get_private_key_size()
get_signature_size()
get_ct_size()
```

These values determine:

* Packet layout
* Memory allocation
* Network serialization
* Authentication message length

If these values are incorrect, the protocol will break.

Example:

| Parameter       | Example Size |
| --------------- | ------------ |
| Public Key      | 1312 bytes   |
| Private Key     | 2528 bytes   |
| Signature       | 2420 bytes   |
| Ciphertext (ct) | 1088 bytes   |

All values must be consistent across:

* Key generation
* Signing
* Verification
* Packet serialization

---

## 6. Data Format Requirements

All cryptographic functions must:

* Use raw binary byte arrays
* Not use strings
* Not use dynamic resizing during protocol execution
* Avoid heap fragmentation where possible
* Be thread-safe

The system may call these functions from multiple threads (RSU environment).

---

## 7. Performance Expectations

The system measures:

* Sign time
* Verify time
* Encapsulation time
* Decapsulation time
* Key derivation time
* Hash time

Your implementation must:

* Not block indefinitely
* Not perform excessive heap allocation
* Avoid debug logging inside crypto functions

Performance is logged and visible in dashboard metrics.

---

## 8. Error Handling Requirements

All failures must:

* Return false (for verification)
* Throw controlled exceptions (if unavoidable)
* Never cause segmentation fault
* Never terminate process

If decapsulation fails:

* Protocol must abort session gracefully
* No undefined behavior allowed

---

## 9. Security Responsibilities

The testbed assumes:

* Secure development environment
* No side-channel mitigation required (unless specified)
* No hardware key protection

If your implementation requires:

* Hardware acceleration
* TPM
* Secure enclaves

These must be documented separately.

---

## 10. Integration Steps

### Step 1

Implement all required functions in:

```
protocol/crypto/lattice_provider.cpp
```

### Step 2

Ensure all size accessors return correct values.

### Step 3

Rebuild:

```
cd protocol/build
make clean && make
```

### Step 4

Update config:

```json
"crypto_provider": "LatticeProvider"
```

### Step 5

Run full system test:

```
./scripts/run_full_system_test.sh
```

If integration is correct:

* Authentication completes successfully
* Packet sizes adjust automatically
* No other code changes required

---

## 11. Common Integration Errors

| Problem                        | Cause                                      |
| ------------------------------ | ------------------------------------------ |
| Packet deserialization failure | Incorrect key or signature size            |
| Session mismatch               | Shared secret length not 32 bytes          |
| KC1/KC2 failure                | Incorrect key derivation                   |
| RSU crash                      | Unhandled exception inside crypto function |
| Authentication timeout         | Slow crypto implementation                 |

---

## 12. What You Must NOT Change

Do NOT modify:

* Packet structure
* Authentication steps
* State machine logic
* UDP communication layer
* Desktop registration flow

If your algorithm cannot fit into this interface, the protocol design must be reviewed.

---

## 13. Support

If any of the following is unclear:

* Memory ownership rules
* Buffer management
* Required size alignment
* Thread safety model

Contact system architect before modifying architecture.

---

# END OF GUIDE

---