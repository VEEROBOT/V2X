#pragma once
/**
 * V2X Protocol — Placeholder Crypto Provider
 *
 * Uses OpenSSL for real crypto operations:
 *   - Hash:      SHA-256
 *   - HMAC:      HMAC-SHA-256
 *   - KEM:       ECDH on P-256 (ephemeral keypair + ECDH = KEM-like)
 *   - Signature: ECDSA P-256
 *   - KDF:       HKDF-SHA-256
 *
 * This provides a fully functional testbed for development.
 * Packets will be smaller than lattice (~456 bytes vs ~4892 bytes)
 * but the protocol flow is identical.
 */

#include "crypto_provider.h"

namespace v2x {

class PlaceholderProvider : public CryptoProvider {
public:
    PlaceholderProvider();
    ~PlaceholderProvider() override;

    // Identity & Registration
    Bytes generate_hash_key(const Bytes& data, const Bytes& secret) override;
    KeyPair generate_keypair() override;
    Bytes generate_partial_private_key(const Bytes& aid,
                                        const Bytes& master_secret) override;

    // KEM
    KEMResult encapsulate(const Bytes& recipient_pk) override;
    Bytes decapsulate(const Bytes& ciphertext, const Bytes& own_sk) override;

    // Signatures
    Bytes sign(const Bytes& message, const Bytes& private_key) override;
    bool verify_signature(const Bytes& signature,
                           const Bytes& message,
                           const Bytes& public_key) override;

    // Hash & HMAC
    Bytes compute_hash(const Bytes& data) override;
    Bytes compute_hmac(const Bytes& key, const Bytes& data) override;

    // Session key derivation
    Bytes derive_master_session_key(const Bytes& shared_secret,
                                     const Bytes& nonce_obu,
                                     const Bytes& nonce_rsu,
                                     const Bytes& session_id) override;
    SessionKeys split_session_key(const Bytes& master_key) override;

    // Authenticated encryption
    Bytes aes_gcm_encrypt(const Bytes& key, const Bytes& plaintext) override;
    Bytes aes_gcm_decrypt(const Bytes& key, const Bytes& ciphertext_with_tag) override;

    // Size accessors (ECDSA/ECDH P-256 sizes)
    size_t get_public_key_size()  const override { return 65; }   // Uncompressed P-256
    size_t get_private_key_size() const override { return 32; }   // P-256 scalar
    size_t get_signature_size()   const override { return 72; }   // DER max for P-256
    size_t get_ct_size()          const override { return 65; }   // Ephemeral PK

    std::string get_provider_name() const override { return "placeholder-ecdsa-p256"; }

private:
    /** Perform ECDH: derive shared secret from own SK and peer PK. */
    Bytes ecdh_derive(const Bytes& own_sk, const Bytes& peer_pk);
};

} // namespace v2x
