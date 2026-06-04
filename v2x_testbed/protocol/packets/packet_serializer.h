#pragma once
/**
 * V2X Protocol — Packet Types and Serializer
 *
 * Handles serialization and deserialization of all V2X packets.
 * Field sizes are determined at runtime by the crypto provider.
 *
 * Wire format: [type:1B] [provider_id:1B] [total_length:4B] [fields...]
 */

#include "crypto/crypto_provider.h"
#include <cstdint>
#include <chrono>

namespace v2x {

// ============================================================================
// Packet Type Codes
// ============================================================================

enum PacketType : uint8_t {
    PKT_AUTH_REQUEST   = 0x10,
    PKT_AUTH_RESPONSE  = 0x11,
    PKT_SESSION_ID     = 0x12,
    PKT_KC1            = 0x13,
    PKT_KC2            = 0x14,
    PKT_POST_AUTH_MSG  = 0x20,
    PKT_ERROR          = 0xFF,
};

enum ProviderID : uint8_t {
    PROVIDER_PLACEHOLDER = 0x01,
    PROVIDER_LATTICE     = 0x02,
};

// ============================================================================
// Packet Structures (deserialized)
// ============================================================================

struct AuthRequest {
    Bytes pid_obu;      // 32 bytes
    Bytes pk_obu;       // variable (provider)
    Bytes ct_obu;       // variable (provider) — KEM capsule
    int64_t ts_obu;     // microseconds since epoch
    Bytes nonce_obu;    // 32 bytes
    Bytes sig_obu;      // variable (provider)
};

struct AuthResponse {
    Bytes pid_rsu;      // 32 bytes
    Bytes pk_rsu;       // variable (provider)
    int64_t ts_rsu;     // microseconds since epoch
    Bytes nonce_rsu;    // 32 bytes
    Bytes nonce_obu;    // 32 bytes (echoed back)
    Bytes sig_rsu;      // variable (provider)
};

struct PostAuthMessage {
    Bytes encrypted_payload;
    Bytes hmac_tag;     // 32 bytes
};

// ============================================================================
// Packet Header (6 bytes)
// ============================================================================

struct PacketHeader {
    uint8_t type;
    uint8_t provider_id;
    uint32_t total_length;
};

constexpr size_t HEADER_SIZE = 6;

// ============================================================================
// PacketSerializer
// ============================================================================

class PacketSerializer {
public:
    explicit PacketSerializer(CryptoProvider* provider);

    // Serialize
    Bytes serialize_auth_request(const AuthRequest& req);
    Bytes serialize_auth_response(const AuthResponse& resp);
    Bytes serialize_session_id(const Bytes& session_id);
    Bytes serialize_kc(PacketType type, const Bytes& kc_value);
    Bytes serialize_post_auth(const Bytes& encrypted, const Bytes& hmac);

    // Deserialize
    PacketHeader deserialize_header(const Bytes& data);
    AuthRequest deserialize_auth_request(const Bytes& data);
    AuthResponse deserialize_auth_response(const Bytes& data);
    Bytes deserialize_session_id(const Bytes& data);
    Bytes deserialize_kc(const Bytes& data);
    PostAuthMessage deserialize_post_auth(const Bytes& data);

    // Size calculations
    size_t get_auth_request_size() const;
    size_t get_auth_response_size() const;

    // Current timestamp in microseconds
    static int64_t now_microseconds();

    // Generate random nonce (32 bytes)
    static Bytes generate_nonce();

private:
    CryptoProvider* crypto_;
    uint8_t provider_id_;

    void write_header(Bytes& out, PacketType type, uint32_t payload_len);
    void write_bytes(Bytes& out, const Bytes& data);
    void write_int64(Bytes& out, int64_t value);

    Bytes read_bytes(const uint8_t*& ptr, size_t len);
    int64_t read_int64(const uint8_t*& ptr);
};

} // namespace v2x
