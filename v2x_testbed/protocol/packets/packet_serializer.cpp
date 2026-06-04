/**
 * File: packet_serializer.cpp
 * Module: V2X Protocol — Packet Serializer
 *
 * Purpose:
 *    Serializes and deserializes all V2X authentication protocol messages.\n *    Implements the 32-step protocol packet formats with binary encoding.
 *
 * Author(s): Praveen Kumar
 * Company: Siliris Technologies Pvt. Ltd
 * Created: 15th February 2026
 * Version: 1.1
 *
 * Packet Types:\n *    - AuthRequest: OBU → RSU (steps 7-19)\n *    - AuthResponse: RSU → OBU (steps 20-26)\n *    - KC1/KC2: Key confirmation messages (steps 27-30)\n *
 * Format: Binary with fixed-size fields, variable-length payloads.
 * All multi-byte fields are big-endian (network byte order).
 *
 * License:
 *    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
 *    Proprietary - See LICENSE file for terms and conditions.
 */

#include "packet_serializer.h"
#include <openssl/rand.h>
#include <cstring>
#include <stdexcept>
#include <arpa/inet.h>

namespace v2x {

PacketSerializer::PacketSerializer(CryptoProvider* provider)
    : crypto_(provider) {
    std::string name = provider->get_provider_name();
    provider_id_ = (name.find("lattice") != std::string::npos)
                   ? PROVIDER_LATTICE : PROVIDER_PLACEHOLDER;
}

// ============================================================================
// Write helpers
// ============================================================================

void PacketSerializer::write_header(Bytes& out, PacketType type, uint32_t payload_len) {
    out.push_back(static_cast<uint8_t>(type));
    out.push_back(provider_id_);
    uint32_t total = htonl(payload_len + HEADER_SIZE);
    const uint8_t* p = reinterpret_cast<const uint8_t*>(&total);
    out.insert(out.end(), p, p + 4);
}

void PacketSerializer::write_bytes(Bytes& out, const Bytes& data) {
    out.insert(out.end(), data.begin(), data.end());
}

void PacketSerializer::write_int64(Bytes& out, int64_t value) {
    // Big-endian
    for (int i = 7; i >= 0; --i) {
        out.push_back(static_cast<uint8_t>((value >> (i * 8)) & 0xFF));
    }
}

Bytes PacketSerializer::read_bytes(const uint8_t*& ptr, size_t len) {
    Bytes result(ptr, ptr + len);
    ptr += len;
    return result;
}

int64_t PacketSerializer::read_int64(const uint8_t*& ptr) {
    int64_t value = 0;
    for (int i = 0; i < 8; ++i) {
        value = (value << 8) | (*ptr++);
    }
    return value;
}

// ============================================================================
// Serialize
// ============================================================================

Bytes PacketSerializer::serialize_auth_request(const AuthRequest& req) {
    // Signature is padded to max size for fixed-field packet format
    size_t sig_max = crypto_->get_signature_size();
    size_t payload_size = 32                            // PID_OBU
                        + crypto_->get_public_key_size() // PK_OBU
                        + crypto_->get_ct_size()         // ct_OBU
                        + 8                              // TS_OBU
                        + 32                             // Nonce_OBU
                        + 2                              // Sig actual length
                        + sig_max;                       // Sig_OBU (padded)

    Bytes out;
    out.reserve(HEADER_SIZE + payload_size);

    write_header(out, PKT_AUTH_REQUEST, payload_size);
    write_bytes(out, req.pid_obu);
    write_bytes(out, req.pk_obu);
    write_bytes(out, req.ct_obu);
    write_int64(out, req.ts_obu);
    write_bytes(out, req.nonce_obu);

    // Write actual signature length (2 bytes BE) + zero-padded signature
    uint16_t sig_len = static_cast<uint16_t>(req.sig_obu.size());
    out.push_back(static_cast<uint8_t>(sig_len >> 8));
    out.push_back(static_cast<uint8_t>(sig_len & 0xFF));
    write_bytes(out, req.sig_obu);
    // Pad to fixed size
    for (size_t i = req.sig_obu.size(); i < sig_max; ++i)
        out.push_back(0);

    return out;
}

Bytes PacketSerializer::serialize_auth_response(const AuthResponse& resp) {
    size_t sig_max = crypto_->get_signature_size();
    size_t payload_size = 32                            // PID_RSU
                        + crypto_->get_public_key_size() // PK_RSU
                        + 8                              // TS_RSU
                        + 32                             // Nonce_RSU
                        + 32                             // Nonce_OBU (echoed)
                        + 2                              // Sig actual length
                        + sig_max;                       // Sig_RSU (padded)

    Bytes out;
    out.reserve(HEADER_SIZE + payload_size);

    write_header(out, PKT_AUTH_RESPONSE, payload_size);
    write_bytes(out, resp.pid_rsu);
    write_bytes(out, resp.pk_rsu);
    write_int64(out, resp.ts_rsu);
    write_bytes(out, resp.nonce_rsu);
    write_bytes(out, resp.nonce_obu);

    // Write actual signature length (2 bytes BE) + zero-padded signature
    uint16_t sig_len = static_cast<uint16_t>(resp.sig_rsu.size());
    out.push_back(static_cast<uint8_t>(sig_len >> 8));
    out.push_back(static_cast<uint8_t>(sig_len & 0xFF));
    write_bytes(out, resp.sig_rsu);
    for (size_t i = resp.sig_rsu.size(); i < sig_max; ++i)
        out.push_back(0);

    return out;
}

Bytes PacketSerializer::serialize_session_id(const Bytes& session_id) {
    Bytes out;
    write_header(out, PKT_SESSION_ID, 32);
    write_bytes(out, session_id);
    return out;
}

Bytes PacketSerializer::serialize_kc(PacketType type, const Bytes& kc_value) {
    Bytes out;
    write_header(out, type, 32);
    write_bytes(out, kc_value);
    return out;
}

Bytes PacketSerializer::serialize_post_auth(const Bytes& encrypted, const Bytes& hmac) {
    Bytes out;
    // Payload: [enc_len:4B] [encrypted] [hmac:32B]
    uint32_t enc_len = static_cast<uint32_t>(encrypted.size());
    size_t payload_size = 4 + encrypted.size() + 32;

    write_header(out, PKT_POST_AUTH_MSG, payload_size);

    uint32_t net_len = htonl(enc_len);
    const uint8_t* p = reinterpret_cast<const uint8_t*>(&net_len);
    out.insert(out.end(), p, p + 4);
    write_bytes(out, encrypted);
    write_bytes(out, hmac);

    return out;
}

// ============================================================================
// Deserialize
// ============================================================================

PacketHeader PacketSerializer::deserialize_header(const Bytes& data) {
    if (data.size() < HEADER_SIZE) {
        throw std::runtime_error("Packet too short for header");
    }
    PacketHeader hdr;
    hdr.type = data[0];
    hdr.provider_id = data[1];
    uint32_t net_len;
    memcpy(&net_len, data.data() + 2, 4);
    hdr.total_length = ntohl(net_len);
    return hdr;
}

AuthRequest PacketSerializer::deserialize_auth_request(const Bytes& data) {
    const uint8_t* ptr = data.data() + HEADER_SIZE; // Skip header

    AuthRequest req;
    req.pid_obu   = read_bytes(ptr, 32);
    req.pk_obu    = read_bytes(ptr, crypto_->get_public_key_size());
    req.ct_obu    = read_bytes(ptr, crypto_->get_ct_size());
    req.ts_obu    = read_int64(ptr);
    req.nonce_obu = read_bytes(ptr, 32);

    // Read actual signature length, then extract only that many bytes
    uint16_t sig_len = (static_cast<uint16_t>(ptr[0]) << 8) | ptr[1];
    ptr += 2;
    req.sig_obu   = read_bytes(ptr, sig_len);
    // Skip padding
    ptr += (crypto_->get_signature_size() - sig_len);

    return req;
}

AuthResponse PacketSerializer::deserialize_auth_response(const Bytes& data) {
    const uint8_t* ptr = data.data() + HEADER_SIZE;

    AuthResponse resp;
    resp.pid_rsu   = read_bytes(ptr, 32);
    resp.pk_rsu    = read_bytes(ptr, crypto_->get_public_key_size());
    resp.ts_rsu    = read_int64(ptr);
    resp.nonce_rsu = read_bytes(ptr, 32);
    resp.nonce_obu = read_bytes(ptr, 32);

    // Read actual signature length, then extract only that many bytes
    uint16_t sig_len = (static_cast<uint16_t>(ptr[0]) << 8) | ptr[1];
    ptr += 2;
    resp.sig_rsu   = read_bytes(ptr, sig_len);
    ptr += (crypto_->get_signature_size() - sig_len);

    return resp;
}

Bytes PacketSerializer::deserialize_session_id(const Bytes& data) {
    const uint8_t* ptr = data.data() + HEADER_SIZE;
    return read_bytes(ptr, 32);
}

Bytes PacketSerializer::deserialize_kc(const Bytes& data) {
    const uint8_t* ptr = data.data() + HEADER_SIZE;
    return read_bytes(ptr, 32);
}

PostAuthMessage PacketSerializer::deserialize_post_auth(const Bytes& data) {
    const uint8_t* ptr = data.data() + HEADER_SIZE;

    uint32_t net_len;
    memcpy(&net_len, ptr, 4);
    ptr += 4;
    uint32_t enc_len = ntohl(net_len);

    PostAuthMessage msg;
    msg.encrypted_payload = read_bytes(ptr, enc_len);
    msg.hmac_tag = read_bytes(ptr, 32);
    return msg;
}

// ============================================================================
// Size calculations
// ============================================================================

size_t PacketSerializer::get_auth_request_size() const {
    return HEADER_SIZE + 32 + crypto_->get_public_key_size()
           + crypto_->get_ct_size() + 8 + 32 + 2 + crypto_->get_signature_size();
}

size_t PacketSerializer::get_auth_response_size() const {
    return HEADER_SIZE + 32 + crypto_->get_public_key_size()
           + 8 + 32 + 32 + 2 + crypto_->get_signature_size();
}

// ============================================================================
// Utility
// ============================================================================

int64_t PacketSerializer::now_microseconds() {
    auto now = std::chrono::system_clock::now();
    auto us = std::chrono::duration_cast<std::chrono::microseconds>(
        now.time_since_epoch()
    );
    return us.count();
}

Bytes PacketSerializer::generate_nonce() {
    Bytes nonce(32);
    if (RAND_bytes(nonce.data(), 32) != 1) {
        throw std::runtime_error("Failed to generate random nonce");
    }
    return nonce;
}

} // namespace v2x
