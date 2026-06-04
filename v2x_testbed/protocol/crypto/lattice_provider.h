#pragma once
/**
 * V2X Protocol — Lattice Crypto Provider (STUB)
 *
 * Customer will provide their NTL-based implementation.
 * All methods throw "Not implemented" until customer delivers.
 * Size accessors return the correct lattice sizes.
 */

#include "crypto_provider.h"

namespace v2x {

class LatticeProvider : public CryptoProvider {
public:
    Bytes generate_hash_key(const Bytes&, const Bytes&) override {
        throw std::runtime_error("LatticeProvider: Not implemented — customer provides");
    }
    KeyPair generate_keypair() override {
        throw std::runtime_error("LatticeProvider: Not implemented — customer provides");
    }
    Bytes generate_partial_private_key(const Bytes&, const Bytes&) override {
        throw std::runtime_error("LatticeProvider: Not implemented — customer provides");
    }
    KEMResult encapsulate(const Bytes&) override {
        throw std::runtime_error("LatticeProvider: Not implemented — customer provides");
    }
    Bytes decapsulate(const Bytes&, const Bytes&) override {
        throw std::runtime_error("LatticeProvider: Not implemented — customer provides");
    }
    Bytes sign(const Bytes&, const Bytes&) override {
        throw std::runtime_error("LatticeProvider: Not implemented — customer provides");
    }
    bool verify_signature(const Bytes&, const Bytes&, const Bytes&) override {
        throw std::runtime_error("LatticeProvider: Not implemented — customer provides");
    }
    Bytes compute_hash(const Bytes&) override {
        throw std::runtime_error("LatticeProvider: Not implemented — customer provides");
    }
    Bytes compute_hmac(const Bytes&, const Bytes&) override {
        throw std::runtime_error("LatticeProvider: Not implemented — customer provides");
    }
    Bytes derive_master_session_key(const Bytes&, const Bytes&,
                                     const Bytes&, const Bytes&) override {
        throw std::runtime_error("LatticeProvider: Not implemented — customer provides");
    }
    SessionKeys split_session_key(const Bytes&) override {
        throw std::runtime_error("LatticeProvider: Not implemented — customer provides");
    }

    // AES-GCM (can reuse OpenSSL implementation — algorithm-independent)
    Bytes aes_gcm_encrypt(const Bytes&, const Bytes&) override {
        throw std::runtime_error("LatticeProvider: Not implemented — customer provides");
    }
    Bytes aes_gcm_decrypt(const Bytes&, const Bytes&) override {
        throw std::runtime_error("LatticeProvider: Not implemented — customer provides");
    }

    // Lattice sizes (from customer's algorithm)
    size_t get_public_key_size()  const override { return 1312; }
    size_t get_private_key_size() const override { return 2528; }
    size_t get_signature_size()   const override { return 2420; }
    size_t get_ct_size()          const override { return 1088; }

    std::string get_provider_name() const override { return "lattice-ntl"; }
};

} // namespace v2x
