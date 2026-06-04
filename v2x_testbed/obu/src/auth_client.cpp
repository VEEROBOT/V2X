/**
 * File: auth_client.cpp
 * Module: V2X Authentication Testbed — OBU Authentication Client
 *
 * Purpose:
 *    Executes the V2X authentication protocol from the OBU perspective.
 *    Implements steps 7-30 of the 32-step protocol: AuthRequest generation,
 *    signature verification, session key derivation, and key confirmation.
 *
 * Author(s): Praveen Kumar
 * Company: Siliris Technologies Pvt. Ltd
 * Created: 15th February 2026
 * Version: 1.1
 *
 * Key Operations:
 *    - Generate PID (PacketID) with current timestamp
 *    - Encrypt payload to RSU public key (KEM encapsulation)
 *    - Sign AuthRequest with private key
 *    - Send to RSU (UDP)
 *    - Verify RSU's AuthResponse signature
 *    - Derive shared session keys using KEM shared secret
 *    - Send KC1 (Key Confirmation 1)
 *    - Verify KC2 response → SESSION ESTABLISHED
 *
 * License:
 *    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
 *    Proprietary - See LICENSE file for terms and conditions.
 */

#include "auth_client.h"
#include "utils/hex_utils.h"
#include <thread>
#include <iostream>
#include <cmath>

namespace v2x {

AuthClient::AuthClient(CryptoProvider* crypto,
                       UdpClient& udp,
                       const RegistrationKeys& keys,
                       const std::string& entity_id,
                       bool is_emergency,
                       int delta_ts_ms,
                       TestMode test_mode)
    : crypto_(crypto),
      serializer_(crypto),
      udp_(udp),
      keys_(keys),
      entity_id_(entity_id),
      is_emergency_(is_emergency),
      delta_ts_us_(delta_ts_ms * 1000),
      test_mode_(test_mode)
{
    master_secret_ = keys_.daid;
}

AuthResult AuthClient::authenticate() {
    AuthResult result;
    result.success = false;
    Timer& timer = result.timing;

    timer.start("total");
    std::cout << "\n[AUTH] Starting authentication for " << entity_id_ << std::endl;

    // =========================================================================
    // Step 1: Generate PID_OBU = Hash(AID || msk || current_time)
    // =========================================================================
    timer.start("pid_gen");
    int64_t pid_ts = PacketSerializer::now_microseconds();
    Bytes ts_bytes(8);
    for (int i = 7; i >= 0; --i)
        ts_bytes[7 - i] = static_cast<uint8_t>((pid_ts >> (i * 8)) & 0xFF);

    Bytes pid_input;
    pid_input.insert(pid_input.end(), keys_.aid.begin(), keys_.aid.end());
    pid_input.insert(pid_input.end(), master_secret_.begin(), master_secret_.end());
    pid_input.insert(pid_input.end(), ts_bytes.begin(), ts_bytes.end());
    Bytes pid_obu = crypto_->compute_hash(pid_input);
    timer.stop("pid_gen");
    std::cout << "[AUTH] Step 1:  PID = " << to_hex(pid_obu, 16) << std::endl;

    // =========================================================================
    // Step 2-3: Encapsulate to RSU's public key
    // =========================================================================
    // Find RSU's PK from peer keys
    Bytes rsu_pk;
    if (!keys_.peer_pks.empty()) {
        rsu_pk = keys_.peer_pks[0].pk;  // RSU should be first peer
    } else {
        // Fallback: use own PK for testing if no peers (shouldn't happen)
        result.failure_reason = "No RSU public key available";
        std::cout << "[AUTH] ✗ " << result.failure_reason << std::endl;
        return result;
    }

    timer.start("encapsulate");
    KEMResult kem = crypto_->encapsulate(rsu_pk);
    timer.stop("encapsulate");
    Bytes ss_obu = kem.shared_secret;
    std::cout << "[AUTH] Step 2-3: Encapsulated. ct=" << kem.ciphertext.size()
              << "B, ss=" << to_hex(ss_obu, 8) << std::endl;

    // =========================================================================
    // Step 4-5: Construct M1 and sign
    // =========================================================================
    int64_t ts_obu = PacketSerializer::now_microseconds();

    if (test_mode_ == TestMode::OLD_TIMESTAMP) {
        std::cout << "[TEST] Using old timestamp..." << std::endl;
        ts_obu -= 60000000; // 60 seconds in microseconds
    }

    Bytes nonce_obu = PacketSerializer::generate_nonce();

    Bytes m1;
    m1.insert(m1.end(), pid_obu.begin(), pid_obu.end());
    m1.insert(m1.end(), keys_.pk_self.begin(), keys_.pk_self.end());
    m1.insert(m1.end(), kem.ciphertext.begin(), kem.ciphertext.end());
    for (int i = 7; i >= 0; --i)
        m1.push_back(static_cast<uint8_t>((ts_obu >> (i * 8)) & 0xFF));
    m1.insert(m1.end(), nonce_obu.begin(), nonce_obu.end());

    timer.start("sign");
    Bytes sig_obu = crypto_->sign(m1, keys_.sk);
    timer.stop("sign");

    if (test_mode_ == TestMode::CORRUPT_SIGNATURE) {
        std::cout << "[TEST] Corrupting signature..." << std::endl;
        if (!sig_obu.empty())
            sig_obu[0] ^= 0xFF;
    }

    std::cout << "[AUTH] Step 5:  Signed. sig=" << sig_obu.size() << "B" << std::endl;

    // =========================================================================
    // Step 6: Send AuthRequest via UDP
    // =========================================================================
    AuthRequest req;
    req.pid_obu = pid_obu;
    req.pk_obu = keys_.pk_self;
    req.ct_obu = kem.ciphertext;
    req.ts_obu = ts_obu;
    req.nonce_obu = nonce_obu;
    req.sig_obu = sig_obu;

    Bytes auth_req_pkt = serializer_.serialize_auth_request(req);
    if (test_mode_ == TestMode::REPLAY && last_auth_request_.empty()) {
        last_auth_request_ = auth_req_pkt;
    }

    std::cout << "[AUTH] Step 6:  Sending AuthRequest (" << auth_req_pkt.size()
              << " bytes)..." << std::endl;
    // Send AuthRequest
    if (!udp_.send_to_rsu(std::vector<uint8_t>(
            auth_req_pkt.begin(),
            auth_req_pkt.end())))
    {
        result.failure_reason = "Failed to send AuthRequest";
        std::cout << "[AUTH] ✗ " << result.failure_reason << std::endl;
        return result;
    }

    // If replay test mode, resend the same packet
    if (test_mode_ == TestMode::REPLAY) {
        std::cout << "[TEST] Replaying same AuthRequest..." << std::endl;

        std::this_thread::sleep_for(std::chrono::milliseconds(100));

        udp_.send_to_rsu(std::vector<uint8_t>(
            last_auth_request_.begin(),
            last_auth_request_.end()
        ));
    }

    // =========================================================================
    // Step 20: Wait for SessionID + AuthResponse
    // =========================================================================
    std::cout << "[AUTH] Step 6:  Sent. Waiting for response..." << std::endl;

    // Receive SessionID packet
    auto sid_raw = udp_.receive(5000); // 5s timeout
    if (!sid_raw.has_value()) {
        result.failure_reason = "Timeout waiting for SessionID";
        std::cout << "[AUTH] ✗ " << result.failure_reason << std::endl;
        return result;
    }

    // Receive AuthResponse packet
    auto resp_raw = udp_.receive(5000);
    if (!resp_raw.has_value()) {
        result.failure_reason = "Timeout waiting for AuthResponse";
        std::cout << "[AUTH] ✗ " << result.failure_reason << std::endl;
        return result;
    }

    int64_t ts_obu_recv = PacketSerializer::now_microseconds();

    Bytes session_id = serializer_.deserialize_session_id(
        Bytes(sid_raw->begin(), sid_raw->end()));
    std::string sid_hex = to_hex(session_id);
    result.session_id_hex = sid_hex;
    std::cout << "[AUTH] Step 20: Received SessionID = " << to_hex(session_id, 16) << std::endl;

    AuthResponse resp = serializer_.deserialize_auth_response(
        Bytes(resp_raw->begin(), resp_raw->end()));
    std::cout << "[AUTH] Step 20: Received AuthResponse" << std::endl;

    // =========================================================================
    // Step 21: Timestamp check
    // =========================================================================
    int64_t ts_diff = std::abs(resp.ts_rsu - ts_obu_recv);
    if (ts_diff > delta_ts_us_) {
        result.failure_reason = "Timestamp check failed: diff=" +
            std::to_string(ts_diff) + "μs";
        std::cout << "[AUTH] ✗ " << result.failure_reason << std::endl;
        return result;
    }
    std::cout << "[AUTH] Step 21: Timestamp OK (diff=" << ts_diff << "μs)" << std::endl;

    // =========================================================================
    // Step 22: Verify RSU signature
    // =========================================================================
    Bytes m2;
    m2.insert(m2.end(), resp.pid_rsu.begin(), resp.pid_rsu.end());
    m2.insert(m2.end(), resp.pk_rsu.begin(), resp.pk_rsu.end());
    for (int i = 7; i >= 0; --i)
        m2.push_back(static_cast<uint8_t>((resp.ts_rsu >> (i * 8)) & 0xFF));
    m2.insert(m2.end(), resp.nonce_rsu.begin(), resp.nonce_rsu.end());
    m2.insert(m2.end(), resp.nonce_obu.begin(), resp.nonce_obu.end());

    timer.start("verify_sig");
    bool sig_valid = crypto_->verify_signature(resp.sig_rsu, m2, resp.pk_rsu);
    timer.stop("verify_sig");

    if (!sig_valid) {
        result.failure_reason = "RSU signature invalid";
        std::cout << "[AUTH] ✗ " << result.failure_reason << std::endl;
        return result;
    }
    std::cout << "[AUTH] Step 22: RSU signature VALID" << std::endl;

    // =========================================================================
    // Step 23-24: Derive session keys (must match RSU's keys)
    // =========================================================================
    timer.start("derive_key");
    Bytes master_key = crypto_->derive_master_session_key(
        ss_obu, nonce_obu, resp.nonce_rsu, session_id);
    SessionKeys sk = crypto_->split_session_key(master_key);
    timer.stop("derive_key");
    std::cout << "[AUTH] Step 24: Keys derived" << std::endl;

    // =========================================================================
    // Step 25-26: Compute and send KC1
    // =========================================================================
    Bytes kc1_input;
    std::string kc1_tag = "KC1";
    kc1_input.insert(kc1_input.end(), kc1_tag.begin(), kc1_tag.end());
    kc1_input.insert(kc1_input.end(), session_id.begin(), session_id.end());
    kc1_input.insert(kc1_input.end(), nonce_obu.begin(), nonce_obu.end());
    kc1_input.insert(kc1_input.end(), resp.nonce_rsu.begin(), resp.nonce_rsu.end());

    timer.start("hmac_kc1");
    Bytes kc1 = crypto_->compute_hmac(sk.sk_mac, kc1_input);
    timer.stop("hmac_kc1");

    Bytes kc1_pkt = serializer_.serialize_kc(PKT_KC1, kc1);
    udp_.send_to_rsu(std::vector<uint8_t>(kc1_pkt.begin(), kc1_pkt.end()));
    std::cout << "[AUTH] Step 26: KC1 sent (" << kc1_pkt.size() << " bytes)" << std::endl;

    // =========================================================================
    // Step 31: Wait for KC2
    // =========================================================================
    auto kc2_raw = udp_.receive(3000); // 3s timeout
    if (!kc2_raw.has_value()) {
        result.failure_reason = "Timeout waiting for KC2";
        std::cout << "[AUTH] ✗ " << result.failure_reason << std::endl;
        return result;
    }

    Bytes recv_kc2 = serializer_.deserialize_kc(
        Bytes(kc2_raw->begin(), kc2_raw->end()));

    // =========================================================================
    // Step 32: Verify KC2
    // =========================================================================
    Bytes kc2_input;
    std::string kc2_tag = "KC2";
    kc2_input.insert(kc2_input.end(), kc2_tag.begin(), kc2_tag.end());
    kc2_input.insert(kc2_input.end(), session_id.begin(), session_id.end());
    kc2_input.insert(kc2_input.end(), resp.nonce_rsu.begin(), resp.nonce_rsu.end());
    kc2_input.insert(kc2_input.end(), nonce_obu.begin(), nonce_obu.end());

    Bytes expected_kc2 = crypto_->compute_hmac(sk.sk_mac, kc2_input);

    if (recv_kc2 != expected_kc2) {
        result.failure_reason = "KC2 verification failed";
        std::cout << "[AUTH] ✗ " << result.failure_reason << std::endl;
        return result;
    }

    double total_us = timer.stop("total");
    result.success = true;
    result.total_latency_ms = total_us / 1000.0;
    result.sk_enc = sk.sk_enc;
    result.sk_mac = sk.sk_mac;
    result.session_id = session_id;

    std::cout << "\n[AUTH] ╔══════════════════════════════════════╗" << std::endl;
    std::cout << "[AUTH] ║   SESSION ESTABLISHED SUCCESSFULLY   ║" << std::endl;
    std::cout << "[AUTH] ╚══════════════════════════════════════╝" << std::endl;
    std::cout << "[AUTH] SessionID:    " << to_hex(session_id, 16) << "..." << std::endl;
    std::cout << "[AUTH] Total time:   " << result.total_latency_ms << " ms" << std::endl;
    std::cout << "[AUTH] Entity:       " << entity_id_
              << (is_emergency_ ? " [EMERGENCY]" : "") << std::endl;

    // Print timing breakdown
    std::cout << "\n[AUTH] Timing Breakdown:" << std::endl;
    for (auto& [op, us] : timer.all_results()) {
        if (op != "total")
            printf("[AUTH]   %-20s %8.1f μs  (%6.3f ms)\n",
                   op.c_str(), us, us / 1000.0);
    }
    std::cout << std::endl;

    return result;
}

// ============================================================================
// Send Post-Auth Encrypted Message
// ============================================================================

bool AuthClient::send_post_auth_message(const Bytes& plaintext,
                                         const Bytes& sk_enc,
                                         const Bytes& sk_mac) {
    // Step 1: Encrypt with AES-256-GCM using sk_enc
    Bytes encrypted = crypto_->aes_gcm_encrypt(sk_enc, plaintext);

    // Step 2: HMAC the encrypted payload with sk_mac
    Bytes hmac = crypto_->compute_hmac(sk_mac, encrypted);

    // Step 3: Serialize post-auth packet
    Bytes packet = serializer_.serialize_post_auth(encrypted, hmac);

    // Step 4: Send via UDP
    if (!udp_.send_to_rsu(std::vector<uint8_t>(packet.begin(), packet.end()))) {
        std::cerr << "[AUTH] Failed to send post-auth message" << std::endl;
        return false;
    }

    std::cout << "[AUTH] Post-auth message sent (" << plaintext.size()
              << " bytes plaintext → " << packet.size() << " bytes on wire)" << std::endl;
    return true;
}

} // namespace v2x
