# V2X Authentication Testbed — Customer Quick Start

**Siliris Technologies Pvt. Ltd**  
**Version:** 1.2 | **Date:** February 2026

---

## What This System Does

This testbed runs a complete 32-step mutual authentication protocol between vehicles (OBU) and roadside infrastructure (RSU). It currently uses ECDSA P-256 as a placeholder. **Your job is to replace the placeholder crypto with your lattice-based algorithms.**

---

## 1. Verify Everything Works (5 minutes)

```bash
# Build everything
cd protocol && mkdir -p build && cd build && cmake .. -DCMAKE_BUILD_TYPE=Release && make -j$(nproc)
cd ../../rsu && mkdir -p build && cd build && cmake .. -DCMAKE_BUILD_TYPE=Release && make -j$(nproc)
cd ../../obu && mkdir -p build && cd build && cmake .. -DCMAKE_BUILD_TYPE=Release && make -j$(nproc)

# Run automated test (starts all services, runs auth + adversarial tests)
cd ~/v2x_testbed
./scripts/run_full_system_test.sh
```

Expected: `ALL TESTS PASSED`. Open `http://localhost:5000` to see the dashboard.

---

## 2. Run Performance Baseline (2 minutes)

```bash
./scripts/run_performance_test.sh
```

This runs 10 authentication cycles and prints throughput. Current baseline: ~5ms per auth, ~2 auth/sec (limited by 500ms inter-cycle delay).

---

## 3. Where Your Code Goes

You modify exactly **one file**:

```
protocol/crypto/lattice_provider.cpp   ← CREATE THIS
```

The interface is defined in:

```
protocol/crypto/crypto_provider.h      ← DO NOT MODIFY
```

The stub with correct size accessors is in:

```
protocol/crypto/lattice_provider.h     ← UPDATE SIZES IF NEEDED
```

### Methods You Must Implement

| Method | What It Does | Output |
|--------|-------------|--------|
| `generate_keypair()` | Create signing/KEM keypair | KeyPair{pk, sk} |
| `generate_hash_key(data, secret)` | Hash-based key derivation | 32 bytes |
| `generate_partial_private_key(aid, master)` | Partial key from AID | Bytes |
| `encapsulate(recipient_pk)` | KEM encapsulate | {ciphertext, shared_secret(32B)} |
| `decapsulate(ct, own_sk)` | KEM decapsulate | shared_secret (32 bytes) |
| `sign(message, sk)` | Sign a message | signature bytes |
| `verify_signature(sig, msg, pk)` | Verify signature | true/false |
| `compute_hash(data)` | SHA-256 equivalent | 32 bytes |
| `compute_hmac(key, data)` | HMAC-SHA-256 equivalent | 32 bytes |
| `derive_master_session_key(ss, n1, n2, sid)` | Key derivation | 64 bytes |
| `split_session_key(master_key)` | Split into enc + mac | {sk_enc(32B), sk_mac(32B)} |
| `aes_gcm_encrypt(key, plaintext)` | AES-256-GCM encrypt | [12B nonce][ciphertext][16B tag] |
| `aes_gcm_decrypt(key, data)` | AES-256-GCM decrypt | plaintext (throws on tamper) |
| `get_provider_name()` | Provider identifier | string (e.g. "lattice-ntl") |

**Note:** `aes_gcm_encrypt`/`decrypt` can reuse OpenSSL directly — they're algorithm-independent.

### Size Accessors (CRITICAL)

Update these in `lattice_provider.h` to match your algorithm's actual sizes:

```cpp
size_t get_public_key_size()  const override { return 1312; }  // your PK size
size_t get_private_key_size() const override { return 2528; }  // your SK size
size_t get_signature_size()   const override { return 2420; }  // your sig size
size_t get_ct_size()          const override { return 1088; }  // your KEM ct size
```

If these are wrong, packet serialization breaks. The protocol adapts automatically to any sizes.

---

## 4. Build and Test Your Provider

```bash
# Rebuild protocol library
cd protocol/build
cmake .. -DCMAKE_BUILD_TYPE=Release && make -j$(nproc)

# Run crypto unit tests (validates all your methods)
./test_crypto

# Run full protocol simulation (32-step + AES-GCM, in-memory)
./test_protocol_flow

# Rebuild RSU and OBU
cd ../../rsu/build && make -j$(nproc)
cd ../../obu/build && make -j$(nproc)
```

---

## 5. Switch to Your Provider

Edit all config files:

```
rsu/config/rsu_config.json       → "crypto_provider": "lattice"
obu/config/obu1_config.json      → "crypto_provider": "lattice"
obu/config/obu2_config.json      → "crypto_provider": "lattice"
```

Then run the full test:

```bash
./scripts/run_full_system_test.sh
```

If your implementation is correct: all tests pass, no other code changes needed.

---

## 6. Compare Performance

Run with your provider and check the dashboard Performance tab:

```bash
./scripts/run_performance_test.sh
```

The dashboard at `http://localhost:5000` → Performance tab shows:

- Crypto operation timing bars (sign, verify, encapsulate, decapsulate)
- Session latency history
- Per-session metrics table with provider name

Compare your lattice numbers against the ECDSA baseline.

---

## What You Should NOT Modify

| File/Directory | Reason |
|---------------|--------|
| `protocol/packets/` | Packet format adapts to your sizes automatically |
| `rsu/src/` | Protocol engine is algorithm-agnostic |
| `obu/src/` | Same — just uses CryptoProvider interface |
| `desktop/` | Registration, logging, dashboard — all independent |
| `protocol/common/` | Utilities, config, timer — no crypto dependency |

If you believe a change is needed outside `protocol/crypto/`, contact us first.

---

## Key Files Reference

```
protocol/crypto/crypto_provider.h          ← Interface definition (read-only)
protocol/crypto/placeholder_provider.cpp   ← Reference implementation (read for examples)
protocol/crypto/lattice_provider.h         ← Your header (update sizes)
protocol/crypto/lattice_provider.cpp       ← YOUR IMPLEMENTATION

docs/CRYPTO_PROVIDER_INTEGRATION_GUIDE.md  ← Full integration contract
docs/PERFORMANCE_TESTING.md                ← Testing procedures
docs/ROADMAP_PHASE2_HARDWARE.md            ← Hardware deployment plan
```

---

## Common Mistakes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Packet deserialization failure` | Wrong size in get_*_size() | Match actual algorithm output sizes |
| `Session key mismatch (KC1 FAIL)` | Shared secret not 32 bytes | Ensure decapsulate returns exactly 32B |
| `Signature INVALID on valid packet` | verify_signature throws instead of returning false | Return false for invalid, never throw |
| `Timeout` | Crypto too slow (>200ms) | Profile and optimize |
| `Segfault in RSU` | Null pointer or buffer overrun in your code | Test with test_crypto first |

---

**Contact:** Siliris Technologies Pvt. Ltd — Praveen Kumar
