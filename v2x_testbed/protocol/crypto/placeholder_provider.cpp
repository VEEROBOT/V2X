/**
 * File: placeholder_provider.cpp
 * Module: V2X Protocol — Placeholder Crypto Provider Implementation
 *
 * Purpose:
 *    Development/testing crypto provider using OpenSSL 3.x API for all operations.
 *    Implements EC P-256 signatures, ECDH key agreement, and SHA-256.
 *    Provides fast development iteration without lattice crypto complexity.
 *
 * Author(s): Praveen Kumar
 * Company: Siliris Technologies Pvt. Ltd
 * Created: 15th February 2026
 * Version: 1.1
 *
 * Algorithms:
 *    - Key Generation: EC P-256 (secp256r1)
 *    - KEM: ECDH-based key encapsulation
 *    - Signing: ECDSA with SHA-256
 *    - Hashing: SHA-256 for all derivations
 *
 * Note: For production, replace with lattice-based provider.
 *
 * License:
 *    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
 *    Proprietary - See LICENSE file for terms and conditions.
 */

/**
 * V2X Protocol — Placeholder Crypto Provider Implementation
 * Uses OpenSSL 3.x API for all operations.
 */

#include "placeholder_provider.h"

#include <openssl/evp.h>
#include <openssl/ec.h>
#include <openssl/ecdsa.h>
#include <openssl/hmac.h>
#include <openssl/kdf.h>
#include <openssl/rand.h>
#include <openssl/err.h>
#include <openssl/core_names.h>
#include <openssl/param_build.h>
#include <openssl/obj_mac.h>

#include <cstring>
#include <stdexcept>
#include <memory>

namespace v2x {

// Helper: get OpenSSL error string
static std::string ssl_error() {
    char buf[256];
    ERR_error_string_n(ERR_get_error(), buf, sizeof(buf));
    return std::string(buf);
}

// RAII wrapper for EVP_PKEY
struct PKeyDeleter { void operator()(EVP_PKEY* p) { EVP_PKEY_free(p); } };
using PKeyPtr = std::unique_ptr<EVP_PKEY, PKeyDeleter>;

// RAII wrapper for EVP_MD_CTX
struct MdCtxDeleter { void operator()(EVP_MD_CTX* p) { EVP_MD_CTX_free(p); } };
using MdCtxPtr = std::unique_ptr<EVP_MD_CTX, MdCtxDeleter>;

// RAII wrapper for EVP_PKEY_CTX
struct PKeyCtxDeleter { void operator()(EVP_PKEY_CTX* p) { EVP_PKEY_CTX_free(p); } };
using PKeyCtxPtr = std::unique_ptr<EVP_PKEY_CTX, PKeyCtxDeleter>;


// ============================================================================
// Helper: Load EC key from raw bytes
// ============================================================================

static PKeyPtr load_ec_private_key(const Bytes& sk_bytes) {
    // To load a raw private scalar into OpenSSL 3.x, we need to also compute
    // the public point (pub = privkey * G). Use low-level EC_GROUP for that.

    BIGNUM* priv_bn = BN_bin2bn(sk_bytes.data(), sk_bytes.size(), nullptr);
    if (!priv_bn) throw std::runtime_error("BN_bin2bn failed");

    // Compute public point from private scalar
    EC_GROUP* group = EC_GROUP_new_by_curve_name(NID_X9_62_prime256v1);
    EC_POINT* pub_point = EC_POINT_new(group);
    if (!EC_POINT_mul(group, pub_point, priv_bn, nullptr, nullptr, nullptr)) {
        BN_free(priv_bn);
        EC_POINT_free(pub_point);
        EC_GROUP_free(group);
        throw std::runtime_error("EC_POINT_mul failed");
    }

    // Serialize public point to uncompressed form
    size_t pub_len = EC_POINT_point2oct(group, pub_point,
                                         POINT_CONVERSION_UNCOMPRESSED,
                                         nullptr, 0, nullptr);
    Bytes pub_bytes(pub_len);
    EC_POINT_point2oct(group, pub_point, POINT_CONVERSION_UNCOMPRESSED,
                       pub_bytes.data(), pub_len, nullptr);

    EC_POINT_free(pub_point);
    EC_GROUP_free(group);

    // Build EVP_PKEY with both private and public components
    OSSL_PARAM_BLD* bld = OSSL_PARAM_BLD_new();
    OSSL_PARAM_BLD_push_utf8_string(bld, OSSL_PKEY_PARAM_GROUP_NAME, "P-256", 0);
    OSSL_PARAM_BLD_push_BN(bld, OSSL_PKEY_PARAM_PRIV_KEY, priv_bn);
    OSSL_PARAM_BLD_push_octet_string(bld, OSSL_PKEY_PARAM_PUB_KEY,
                                      pub_bytes.data(), pub_bytes.size());

    OSSL_PARAM* params = OSSL_PARAM_BLD_to_param(bld);

    EVP_PKEY_CTX* fctx = EVP_PKEY_CTX_new_from_name(nullptr, "EC", nullptr);
    EVP_PKEY_fromdata_init(fctx);

    EVP_PKEY* pkey = nullptr;
    if (EVP_PKEY_fromdata(fctx, &pkey, EVP_PKEY_KEYPAIR, params) <= 0) {
        OSSL_PARAM_free(params);
        OSSL_PARAM_BLD_free(bld);
        BN_free(priv_bn);
        EVP_PKEY_CTX_free(fctx);
        throw std::runtime_error("Failed to load EC private key: " + ssl_error());
    }

    OSSL_PARAM_free(params);
    OSSL_PARAM_BLD_free(bld);
    BN_free(priv_bn);
    EVP_PKEY_CTX_free(fctx);

    return PKeyPtr(pkey);
}

static PKeyPtr load_ec_public_key(const Bytes& pk_bytes) {
    OSSL_PARAM_BLD* bld = OSSL_PARAM_BLD_new();
    OSSL_PARAM_BLD_push_utf8_string(bld, OSSL_PKEY_PARAM_GROUP_NAME, "P-256", 0);
    OSSL_PARAM_BLD_push_octet_string(bld, OSSL_PKEY_PARAM_PUB_KEY,
                                      pk_bytes.data(), pk_bytes.size());
    OSSL_PARAM* params = OSSL_PARAM_BLD_to_param(bld);

    EVP_PKEY_CTX* fctx = EVP_PKEY_CTX_new_from_name(nullptr, "EC", nullptr);
    EVP_PKEY_fromdata_init(fctx);

    EVP_PKEY* pkey = nullptr;
    EVP_PKEY_fromdata(fctx, &pkey, EVP_PKEY_PUBLIC_KEY, params);

    OSSL_PARAM_free(params);
    OSSL_PARAM_BLD_free(bld);
    EVP_PKEY_CTX_free(fctx);

    if (!pkey) throw std::runtime_error("Failed to load EC public key: " + ssl_error());
    return PKeyPtr(pkey);
}

static PKeyPtr generate_ec_keypair() {
    EVP_PKEY* pkey = nullptr;
    EVP_PKEY_CTX* ctx = EVP_PKEY_CTX_new_from_name(nullptr, "EC", nullptr);
    if (!ctx) throw std::runtime_error("Failed to create keygen context");

    if (EVP_PKEY_keygen_init(ctx) <= 0) {
        EVP_PKEY_CTX_free(ctx);
        throw std::runtime_error("keygen_init failed");
    }

    OSSL_PARAM params[2];
    params[0] = OSSL_PARAM_construct_utf8_string(OSSL_PKEY_PARAM_GROUP_NAME,
                                                   (char*)"P-256", 0);
    params[1] = OSSL_PARAM_construct_end();

    if (EVP_PKEY_CTX_set_params(ctx, params) <= 0) {
        EVP_PKEY_CTX_free(ctx);
        throw std::runtime_error("set_params failed");
    }

    if (EVP_PKEY_generate(ctx, &pkey) <= 0) {
        EVP_PKEY_CTX_free(ctx);
        throw std::runtime_error("keygen failed: " + ssl_error());
    }

    EVP_PKEY_CTX_free(ctx);
    return PKeyPtr(pkey);
}

// Extract raw private key bytes (32 bytes for P-256)
static Bytes extract_private_key(EVP_PKEY* pkey) {
    BIGNUM* bn = nullptr;
    if (!EVP_PKEY_get_bn_param(pkey, OSSL_PKEY_PARAM_PRIV_KEY, &bn)) {
        throw std::runtime_error("Failed to extract private key");
    }
    Bytes result(32, 0);
    BN_bn2binpad(bn, result.data(), 32);
    BN_free(bn);
    return result;
}

// Extract raw public key bytes (65 bytes uncompressed for P-256)
static Bytes extract_public_key(EVP_PKEY* pkey) {
    size_t len = 0;
    if (!EVP_PKEY_get_octet_string_param(pkey, OSSL_PKEY_PARAM_PUB_KEY,
                                          nullptr, 0, &len)) {
        throw std::runtime_error("Failed to get public key size");
    }
    Bytes result(len);
    if (!EVP_PKEY_get_octet_string_param(pkey, OSSL_PKEY_PARAM_PUB_KEY,
                                          result.data(), result.size(), &len)) {
        throw std::runtime_error("Failed to extract public key");
    }
    result.resize(len);
    return result;
}


// ============================================================================
// PlaceholderProvider Implementation
// ============================================================================

PlaceholderProvider::PlaceholderProvider() {
    // OpenSSL 3.x auto-initializes
}

PlaceholderProvider::~PlaceholderProvider() = default;


Bytes PlaceholderProvider::generate_hash_key(const Bytes& data, const Bytes& secret) {
    Bytes combined;
    combined.insert(combined.end(), data.begin(), data.end());
    combined.insert(combined.end(), secret.begin(), secret.end());
    return compute_hash(combined);
}


KeyPair PlaceholderProvider::generate_keypair() {
    auto pkey = generate_ec_keypair();
    KeyPair kp;
    kp.private_key = extract_private_key(pkey.get());
    kp.public_key = extract_public_key(pkey.get());
    return kp;
}


Bytes PlaceholderProvider::generate_partial_private_key(const Bytes& aid,
                                                         const Bytes& master_secret) {
    // Simplified: DAID = Hash(AID || master_secret || "DAID")
    Bytes input;
    input.insert(input.end(), aid.begin(), aid.end());
    input.insert(input.end(), master_secret.begin(), master_secret.end());
    const char* tag = "DAID";
    input.insert(input.end(), tag, tag + 4);
    return compute_hash(input);
}


KEMResult PlaceholderProvider::encapsulate(const Bytes& recipient_pk) {
    // KEM via ECDH:
    // 1. Generate ephemeral keypair
    // 2. Ciphertext = ephemeral public key
    // 3. Shared secret = Hash(ECDH(ephemeral_sk, recipient_pk))

    auto ephemeral = generate_ec_keypair();
    Bytes eph_sk = extract_private_key(ephemeral.get());
    Bytes eph_pk = extract_public_key(ephemeral.get());

    Bytes raw_ss = ecdh_derive(eph_sk, recipient_pk);
    Bytes ss = compute_hash(raw_ss); // Hash the raw ECDH output

    KEMResult result;
    result.ciphertext = eph_pk;      // ct = ephemeral public key
    result.shared_secret = ss;        // ss = Hash(ECDH result)
    return result;
}


Bytes PlaceholderProvider::decapsulate(const Bytes& ciphertext, const Bytes& own_sk) {
    // Reverse of encapsulate:
    // ciphertext = ephemeral public key
    // shared_secret = Hash(ECDH(own_sk, ephemeral_pk))

    Bytes raw_ss = ecdh_derive(own_sk, ciphertext);
    return compute_hash(raw_ss);
}


Bytes PlaceholderProvider::sign(const Bytes& message, const Bytes& private_key) {
    auto pkey = load_ec_private_key(private_key);

    MdCtxPtr md_ctx(EVP_MD_CTX_new());
    if (!md_ctx) throw std::runtime_error("Failed to create MD context");

    if (EVP_DigestSignInit(md_ctx.get(), nullptr, EVP_sha256(), nullptr, pkey.get()) <= 0) {
        throw std::runtime_error("DigestSignInit failed: " + ssl_error());
    }

    if (EVP_DigestSignUpdate(md_ctx.get(), message.data(), message.size()) <= 0) {
        throw std::runtime_error("DigestSignUpdate failed");
    }

    size_t sig_len = 0;
    if (EVP_DigestSignFinal(md_ctx.get(), nullptr, &sig_len) <= 0) {
        throw std::runtime_error("DigestSignFinal (size) failed");
    }

    Bytes signature(sig_len);
    if (EVP_DigestSignFinal(md_ctx.get(), signature.data(), &sig_len) <= 0) {
        throw std::runtime_error("DigestSignFinal failed: " + ssl_error());
    }

    signature.resize(sig_len);
    return signature;
}


bool PlaceholderProvider::verify_signature(const Bytes& signature,
                                            const Bytes& message,
                                            const Bytes& public_key) {
    auto pkey = load_ec_public_key(public_key);

    MdCtxPtr md_ctx(EVP_MD_CTX_new());
    if (!md_ctx) return false;

    if (EVP_DigestVerifyInit(md_ctx.get(), nullptr, EVP_sha256(), nullptr, pkey.get()) <= 0) {
        return false;
    }

    if (EVP_DigestVerifyUpdate(md_ctx.get(), message.data(), message.size()) <= 0) {
        return false;
    }

    int result = EVP_DigestVerifyFinal(md_ctx.get(), signature.data(), signature.size());
    return (result == 1);
}


Bytes PlaceholderProvider::compute_hash(const Bytes& data) {
    Bytes hash(32);
    unsigned int len = 0;

    EVP_MD_CTX* ctx = EVP_MD_CTX_new();
    EVP_DigestInit_ex(ctx, EVP_sha256(), nullptr);
    EVP_DigestUpdate(ctx, data.data(), data.size());
    EVP_DigestFinal_ex(ctx, hash.data(), &len);
    EVP_MD_CTX_free(ctx);

    hash.resize(len);
    return hash;
}


Bytes PlaceholderProvider::compute_hmac(const Bytes& key, const Bytes& data) {
    Bytes result(32);
    unsigned int len = 0;

    HMAC(EVP_sha256(), key.data(), key.size(),
         data.data(), data.size(), result.data(), &len);

    result.resize(len);
    return result;
}


Bytes PlaceholderProvider::derive_master_session_key(const Bytes& shared_secret,
                                                      const Bytes& nonce_obu,
                                                      const Bytes& nonce_rsu,
                                                      const Bytes& session_id) {
    // HKDF-SHA-256: IKM=shared_secret, salt=nonces+session_id, info="V2X-SESSION"
    // Output: 64 bytes (will be split into SK_enc + SK_mac)

    Bytes salt;
    salt.insert(salt.end(), nonce_obu.begin(), nonce_obu.end());
    salt.insert(salt.end(), nonce_rsu.begin(), nonce_rsu.end());
    salt.insert(salt.end(), session_id.begin(), session_id.end());

    const char* info_str = "V2X-SESSION-KEY";
    Bytes info(info_str, info_str + strlen(info_str));

    // HKDF via EVP_KDF
    EVP_KDF* kdf = EVP_KDF_fetch(nullptr, "HKDF", nullptr);
    if (!kdf) throw std::runtime_error("HKDF fetch failed");

    EVP_KDF_CTX* kctx = EVP_KDF_CTX_new(kdf);
    EVP_KDF_free(kdf);
    if (!kctx) throw std::runtime_error("HKDF ctx failed");

    OSSL_PARAM params[6];
    int idx = 0;
    params[idx++] = OSSL_PARAM_construct_utf8_string(OSSL_KDF_PARAM_DIGEST,
                                                      (char*)"SHA256", 0);
    params[idx++] = OSSL_PARAM_construct_octet_string(OSSL_KDF_PARAM_KEY,
                                                       (void*)shared_secret.data(),
                                                       shared_secret.size());
    params[idx++] = OSSL_PARAM_construct_octet_string(OSSL_KDF_PARAM_SALT,
                                                       (void*)salt.data(), salt.size());
    params[idx++] = OSSL_PARAM_construct_octet_string(OSSL_KDF_PARAM_INFO,
                                                       (void*)info.data(), info.size());
    params[idx++] = OSSL_PARAM_construct_end();

    Bytes master_key(64);
    if (EVP_KDF_derive(kctx, master_key.data(), 64, params) <= 0) {
        EVP_KDF_CTX_free(kctx);
        throw std::runtime_error("HKDF derive failed: " + ssl_error());
    }

    EVP_KDF_CTX_free(kctx);
    return master_key;
}


SessionKeys PlaceholderProvider::split_session_key(const Bytes& master_key) {
    if (master_key.size() != 64) {
        throw std::runtime_error("Master key must be 64 bytes");
    }
    SessionKeys keys;
    keys.sk_enc.assign(master_key.begin(), master_key.begin() + 32);
    keys.sk_mac.assign(master_key.begin() + 32, master_key.end());
    return keys;
}


Bytes PlaceholderProvider::ecdh_derive(const Bytes& own_sk, const Bytes& peer_pk) {
    auto sk_key = load_ec_private_key(own_sk);
    auto pk_key = load_ec_public_key(peer_pk);

    EVP_PKEY_CTX* ctx = EVP_PKEY_CTX_new(sk_key.get(), nullptr);
    if (!ctx) throw std::runtime_error("ECDH context failed");

    if (EVP_PKEY_derive_init(ctx) <= 0) {
        EVP_PKEY_CTX_free(ctx);
        throw std::runtime_error("ECDH derive_init failed");
    }

    if (EVP_PKEY_derive_set_peer(ctx, pk_key.get()) <= 0) {
        EVP_PKEY_CTX_free(ctx);
        throw std::runtime_error("ECDH set_peer failed: " + ssl_error());
    }

    size_t ss_len = 0;
    if (EVP_PKEY_derive(ctx, nullptr, &ss_len) <= 0) {
        EVP_PKEY_CTX_free(ctx);
        throw std::runtime_error("ECDH derive (size) failed");
    }

    Bytes shared_secret(ss_len);
    if (EVP_PKEY_derive(ctx, shared_secret.data(), &ss_len) <= 0) {
        EVP_PKEY_CTX_free(ctx);
        throw std::runtime_error("ECDH derive failed: " + ssl_error());
    }

    EVP_PKEY_CTX_free(ctx);
    shared_secret.resize(ss_len);
    return shared_secret;
}

// ============================================================================
// AES-256-GCM Encrypt
// ============================================================================

Bytes PlaceholderProvider::aes_gcm_encrypt(const Bytes& key, const Bytes& plaintext) {
    if (key.size() != 32)
        throw std::runtime_error("AES-GCM key must be 32 bytes");

    // Generate random 12-byte nonce
    Bytes nonce(12);
    RAND_bytes(nonce.data(), 12);

    EVP_CIPHER_CTX* ctx = EVP_CIPHER_CTX_new();
    if (!ctx) throw std::runtime_error("EVP_CIPHER_CTX_new failed");

    if (EVP_EncryptInit_ex(ctx, EVP_aes_256_gcm(), nullptr, nullptr, nullptr) != 1) {
        EVP_CIPHER_CTX_free(ctx);
        throw std::runtime_error("AES-GCM init failed");
    }

    if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN, 12, nullptr) != 1) {
        EVP_CIPHER_CTX_free(ctx);
        throw std::runtime_error("AES-GCM set IV len failed");
    }

    if (EVP_EncryptInit_ex(ctx, nullptr, nullptr, key.data(), nonce.data()) != 1) {
        EVP_CIPHER_CTX_free(ctx);
        throw std::runtime_error("AES-GCM encrypt init failed");
    }

    Bytes ciphertext(plaintext.size());
    int out_len = 0;
    if (EVP_EncryptUpdate(ctx, ciphertext.data(), &out_len,
                          plaintext.data(), plaintext.size()) != 1) {
        EVP_CIPHER_CTX_free(ctx);
        throw std::runtime_error("AES-GCM encrypt update failed");
    }

    int final_len = 0;
    if (EVP_EncryptFinal_ex(ctx, ciphertext.data() + out_len, &final_len) != 1) {
        EVP_CIPHER_CTX_free(ctx);
        throw std::runtime_error("AES-GCM encrypt final failed");
    }

    Bytes tag(16);
    if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_GET_TAG, 16, tag.data()) != 1) {
        EVP_CIPHER_CTX_free(ctx);
        throw std::runtime_error("AES-GCM get tag failed");
    }

    EVP_CIPHER_CTX_free(ctx);

    // Output: [12B nonce] [ciphertext] [16B tag]
    Bytes result;
    result.reserve(12 + ciphertext.size() + 16);
    result.insert(result.end(), nonce.begin(), nonce.end());
    result.insert(result.end(), ciphertext.begin(), ciphertext.end());
    result.insert(result.end(), tag.begin(), tag.end());
    return result;
}

// ============================================================================
// AES-256-GCM Decrypt
// ============================================================================

Bytes PlaceholderProvider::aes_gcm_decrypt(const Bytes& key, const Bytes& data) {
    if (key.size() != 32)
        throw std::runtime_error("AES-GCM key must be 32 bytes");
    if (data.size() < 12 + 16)
        throw std::runtime_error("AES-GCM data too short");

    // Parse: [12B nonce] [ciphertext] [16B tag]
    Bytes nonce(data.begin(), data.begin() + 12);
    Bytes ciphertext(data.begin() + 12, data.end() - 16);
    Bytes tag(data.end() - 16, data.end());

    EVP_CIPHER_CTX* ctx = EVP_CIPHER_CTX_new();
    if (!ctx) throw std::runtime_error("EVP_CIPHER_CTX_new failed");

    if (EVP_DecryptInit_ex(ctx, EVP_aes_256_gcm(), nullptr, nullptr, nullptr) != 1) {
        EVP_CIPHER_CTX_free(ctx);
        throw std::runtime_error("AES-GCM decrypt init failed");
    }

    EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN, 12, nullptr);
    EVP_DecryptInit_ex(ctx, nullptr, nullptr, key.data(), nonce.data());

    Bytes plaintext(ciphertext.size());
    int out_len = 0;
    EVP_DecryptUpdate(ctx, plaintext.data(), &out_len,
                      ciphertext.data(), ciphertext.size());

    // Set expected tag
    EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_TAG, 16, (void*)tag.data());

    int final_len = 0;
    int ret = EVP_DecryptFinal_ex(ctx, plaintext.data() + out_len, &final_len);
    EVP_CIPHER_CTX_free(ctx);

    if (ret != 1)
        throw std::runtime_error("AES-GCM authentication failed — tampered data");

    plaintext.resize(out_len + final_len);
    return plaintext;
}

} // namespace v2x
