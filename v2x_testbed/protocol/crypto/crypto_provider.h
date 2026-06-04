#pragma once
/**
 * V2X Protocol — Cryptographic Provider Interface
 *
 * Abstract interface for all cryptographic operations.
 * Implementations:
 *   - PlaceholderProvider: SHA-256 + ECDSA/ECDH (OpenSSL) for development
 *   - LatticeProvider:    Customer's NTL-based lattice crypto (stub)
 *
 * The entire protocol engine calls ONLY through this interface.
 * Swapping providers requires zero changes to protocol code.
 */

#include <cstdint>
#include <cstddef>
#include <vector>
#include <string>
#include <stdexcept>

namespace v2x {

// Convenience type aliases
using Bytes = std::vector<uint8_t>;

// Key encapsulation result
struct KEMResult {
    Bytes ciphertext;    // ct (capsule) — sent to peer
    Bytes shared_secret; // ss — kept locally (always 32 bytes)
};

// Session key pair derived from master key
struct SessionKeys {
    Bytes sk_enc; // 32 bytes — for encryption (AES-256-GCM)
    Bytes sk_mac; // 32 bytes — for HMAC (KC1/KC2)
};

// Keypair
struct KeyPair {
    Bytes public_key;
    Bytes private_key;
};


class CryptoProvider {
public:
    virtual ~CryptoProvider() = default;

    // =========================================================================
    // IDENTITY & REGISTRATION
    // =========================================================================

    /** Hash-based key derivation: Hash(data || secret) → 32 bytes */
    virtual Bytes generate_hash_key(const Bytes& data, const Bytes& secret) = 0;

    /** Generate a full keypair. Returns (PK, SK). */
    virtual KeyPair generate_keypair() = 0;

    /** Generate partial private key from AID + master secret. */
    virtual Bytes generate_partial_private_key(const Bytes& aid,
                                                const Bytes& master_secret) = 0;

    // =========================================================================
    // KEY ENCAPSULATION MECHANISM (KEM)
    // =========================================================================

    /**
     * Encapsulate: Given recipient's PK, produce (ciphertext, shared_secret).
     * The ciphertext is sent to the recipient.
     * The shared_secret is kept locally.
     */
    virtual KEMResult encapsulate(const Bytes& recipient_pk) = 0;

    /**
     * Decapsulate: Given ciphertext and own SK, recover the shared_secret.
     * Must produce the same shared_secret as the encapsulator.
     */
    virtual Bytes decapsulate(const Bytes& ciphertext, const Bytes& own_sk) = 0;

    // =========================================================================
    // DIGITAL SIGNATURES
    // =========================================================================

    /** Sign a message with own private key. */
    virtual Bytes sign(const Bytes& message, const Bytes& private_key) = 0;

    /** Verify a signature against a message and sender's public key. */
    virtual bool verify_signature(const Bytes& signature,
                                   const Bytes& message,
                                   const Bytes& public_key) = 0;

    // =========================================================================
    // HASHING & HMAC
    // =========================================================================

    /** SHA-256 hash of data → 32 bytes. */
    virtual Bytes compute_hash(const Bytes& data) = 0;

    /** HMAC-SHA-256(key, data) → 32 bytes. */
    virtual Bytes compute_hmac(const Bytes& key, const Bytes& data) = 0;

    // =========================================================================
    // SESSION KEY DERIVATION
    // =========================================================================

    /**
     * Derive master session key from shared secret + nonces + session ID.
     * Returns 64 bytes (will be split into SK_enc + SK_mac).
     */
    virtual Bytes derive_master_session_key(const Bytes& shared_secret,
                                             const Bytes& nonce_obu,
                                             const Bytes& nonce_rsu,
                                             const Bytes& session_id) = 0;

    /**
     * Split 64-byte master key into SK_enc (32) + SK_mac (32).
     */
    virtual SessionKeys split_session_key(const Bytes& master_key) = 0;

    // =========================================================================
    // AUTHENTICATED ENCRYPTION (Post-auth messaging)
    // =========================================================================

    /**
     * AES-256-GCM encrypt.
     * Returns: [12B nonce] [ciphertext] [16B GCM tag]
     */
    virtual Bytes aes_gcm_encrypt(const Bytes& key, const Bytes& plaintext) = 0;

    /**
     * AES-256-GCM decrypt.
     * Input: [12B nonce] [ciphertext] [16B GCM tag]
     * Returns plaintext on success, throws on auth failure.
     */
    virtual Bytes aes_gcm_decrypt(const Bytes& key, const Bytes& ciphertext_with_tag) = 0;

    // =========================================================================
    // SIZE ACCESSORS — Critical for packet serialization
    // =========================================================================

    virtual size_t get_public_key_size()  const = 0;
    virtual size_t get_private_key_size() const = 0;
    virtual size_t get_signature_size()   const = 0;
    virtual size_t get_ct_size()          const = 0;

    // =========================================================================
    // PROVIDER INFO
    // =========================================================================

    virtual std::string get_provider_name() const = 0;
};

} // namespace v2x
