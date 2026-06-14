/**
 * File: packet_processor.cpp
 * Module: V2X Authentication Testbed — RSU Packet Processor
 *
 * Purpose:
 *    Core state machine for processing V2X authentication packets from OBUs.
 *    Handles the complete 32-step protocol flow: signature verification,
 *    session creation, key derivation, and authentication confirmation.
 *
 * Author(s): Praveen Kumar
 * Company: Siliris Technologies Pvt. Ltd
 * Created: 15th February 2026
 * Version: 1.1
 *
 * Key Operations:
 *    Steps 7-19: Receive AuthRequest, verify OBU timestamp and signature
 *                Decrypt payload, create session, generate AuthResponse
 *    Steps 20-26: Receive OBU's KC1, verify signature\n *                 Generate shared keys, send KC2\n *    Steps 27-30: Final confirmation → SESSION ESTABLISHED\n *
 * License:
 *    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
 *    Proprietary - See LICENSE file for terms and conditions.
 */

#include "packet_processor.h"
#include "utils/hex_utils.h"

#include <iostream>
#include <sstream>
#include <iomanip>
#include <chrono>
#include <cmath>

namespace v2x {

PacketProcessor::PacketProcessor(CryptoProvider* crypto,
                                 ReceiveBuffer& buffer,
                                 UdpServer& udp,
                                 SessionManager& sessions,
                                 LogSender& logger,
                                 const RegistrationKeys& keys,
                                 int delta_ts_ms,
                                 const std::string& car_alert_ip,
                                 int car_alert_port)
    : crypto_(crypto), serializer_(crypto), buffer_(buffer), udp_(udp),
      sessions_(sessions), logger_(logger), keys_(keys),
      delta_ts_us_(delta_ts_ms * 1000), running_(false),
      car_alert_ip_(car_alert_ip), car_alert_port_(car_alert_port)
{
    // Master secret = DAID (used for PID generation)
    master_secret_ = keys_.daid;
}

void PacketProcessor::send_car_alert(bool active, const std::string& session_id_hex) {
    if (car_alert_ip_.empty()) return;

    std::string msg;
    if (active) {
        msg = "{\"type\":\"EMERGENCY_ACTIVE\",\"session_id\":\"" + session_id_hex + "\"}";
    } else {
        msg = "{\"type\":\"EMERGENCY_CLEARED\"}";
    }

    std::vector<uint8_t> payload(msg.begin(), msg.end());
    bool ok = udp_.send_to(payload, car_alert_ip_, car_alert_port_);
    if (ok) {
        std::cout << "[RSU] Car alert sent → " << car_alert_ip_ << ":"
                  << car_alert_port_ << " : " << msg << std::endl;
    } else {
        std::cout << "[RSU] WARNING: Failed to send car alert to "
                  << car_alert_ip_ << ":" << car_alert_port_ << std::endl;
    }
}

void PacketProcessor::start() {
    running_ = true;
    thread_ = std::thread(&PacketProcessor::process_loop, this);
    std::cout << "[PROC] Packet processor started" << std::endl;
}

void PacketProcessor::stop() {
    running_ = false;
    if (thread_.joinable()) thread_.join();
}

void PacketProcessor::process_loop() {
    while (running_) {
        auto pkt = buffer_.pop();
        if (pkt.has_value()) {
            handle_packet(pkt.value());
        } else {
            // Buffer empty — wait a bit
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
    }
}

void PacketProcessor::handle_packet(const ReceiveBuffer::Packet& pkt) {
    if (pkt.data.size() < HEADER_SIZE) {
        std::cout << "[PROC] Packet too small (" << pkt.data.size()
                  << " bytes), ignoring" << std::endl;
        return;
    }

    PacketHeader hdr = serializer_.deserialize_header(
        Bytes(pkt.data.begin(), pkt.data.end()));

    switch (hdr.type) {
        case PKT_AUTH_REQUEST:
            handle_auth_request(Bytes(pkt.data.begin(), pkt.data.end()),
                               pkt.sender_ip, pkt.sender_port);
            break;
        case PKT_KC1:
            handle_kc1(Bytes(pkt.data.begin(), pkt.data.end()),
                       pkt.sender_ip, pkt.sender_port);
            break;
        case PKT_POST_AUTH_MSG:
            handle_post_auth(Bytes(pkt.data.begin(), pkt.data.end()),
                             pkt.sender_ip, pkt.sender_port);
            break;
        default:
            std::cout << "[PROC] Unknown packet type 0x" << std::hex
                      << (int)hdr.type << std::dec << std::endl;
    }
}

// ============================================================================
// Handle AuthRequest (LLD Steps 7-19)
// ============================================================================

void PacketProcessor::handle_auth_request(const Bytes& data,
                                           const std::string& sender_ip,
                                           int sender_port) {
    Timer timer;
    timer.start("total");

    std::cout << "[PROC] AuthRequest from " << sender_ip << ":" << sender_port << std::endl;

    if (data.size() < serializer_.get_auth_request_size()) {
        std::cout << "[PROC] AuthRequest too small (" << data.size()
                  << " bytes, expected " << serializer_.get_auth_request_size()
                  << "), ignoring" << std::endl;
        return;
    }

    // Step 7: Deserialize
    AuthRequest req = serializer_.deserialize_auth_request(data);
    int64_t ts_recv = PacketSerializer::now_microseconds();

    std::string pid_hex = to_hex(req.pid_obu, 16);

    // -------------------------------------------------------------------------
    // Replay Protection: Reject duplicate PID
    // -------------------------------------------------------------------------
    if (seen_pids_.find(pid_hex) != seen_pids_.end()) {
        std::cout << "[PROC] ✗ REPLAY DETECTED for PID=" << pid_hex << std::endl;
        log_event("REPLAY_DETECTED", pid_hex, "RSU", "", "{}", timer);
        return;
    }

    // Mark PID as seen
    seen_pids_.insert(pid_hex);

    log_event("AUTH_REQUEST_RECEIVED", pid_hex, "RSU", "", "{}", timer);

    // Step 8: Timestamp check
    int64_t ts_diff = std::abs(req.ts_obu - ts_recv);
    if (ts_diff > delta_ts_us_) {
        std::cout << "[PROC] ✗ Timestamp FAILED: diff=" << ts_diff
                  << "μs > threshold=" << delta_ts_us_ << "μs" << std::endl;
        log_event("TIMESTAMP_CHECK_FAIL", pid_hex, "RSU", "",
                  "{\"diff_us\":" + std::to_string(ts_diff) + "}", timer);
        return;
    }
    std::cout << "[PROC] Step 8: Timestamp OK (diff=" << ts_diff << "μs)" << std::endl;
    log_event("TIMESTAMP_CHECK_PASS", pid_hex, "RSU", "",
              "{\"diff_us\":" + std::to_string(ts_diff) + "}", timer);

    // Step 9: Verify signature
    // Reconstruct M1 = PID || PK || ct || TS || Nonce
    Bytes m1;
    m1.insert(m1.end(), req.pid_obu.begin(), req.pid_obu.end());
    m1.insert(m1.end(), req.pk_obu.begin(), req.pk_obu.end());
    m1.insert(m1.end(), req.ct_obu.begin(), req.ct_obu.end());
    for (int i = 7; i >= 0; --i)
        m1.push_back(static_cast<uint8_t>((req.ts_obu >> (i * 8)) & 0xFF));
    m1.insert(m1.end(), req.nonce_obu.begin(), req.nonce_obu.end());

    timer.start("verify_signature");
    bool sig_valid = crypto_->verify_signature(req.sig_obu, m1, req.pk_obu);
    timer.stop("verify_signature");

    if (!sig_valid) {
        std::cout << "[PROC] ✗ Signature INVALID" << std::endl;
        log_event("SIGNATURE_CHECK_FAIL", pid_hex, "RSU", "", "{}", timer);
        return;
    }
    std::cout << "[PROC] Step 9: Signature VALID" << std::endl;
    log_event("SIGNATURE_CHECK_PASS", pid_hex, "RSU", "", "{}", timer);

    // Step 10: Decapsulate
    timer.start("decapsulate");
    Bytes ss = crypto_->decapsulate(req.ct_obu, keys_.sk);
    timer.stop("decapsulate");
    std::cout << "[PROC] Step 10: Decapsulated. ss=" << to_hex(ss, 8) << std::endl;
    log_event("DECAPSULATION_COMPLETE", pid_hex, "RSU", "", "{}", timer);

    // Step 11: Generate PID_RSU
    timer.start("pid_gen");
    int64_t ts_rsu = PacketSerializer::now_microseconds();
    Bytes ts_bytes(8);
    for (int i = 7; i >= 0; --i)
        ts_bytes[7 - i] = static_cast<uint8_t>((ts_rsu >> (i * 8)) & 0xFF);

    Bytes pid_input;
    pid_input.insert(pid_input.end(), keys_.aid.begin(), keys_.aid.end());
    pid_input.insert(pid_input.end(), master_secret_.begin(), master_secret_.end());
    pid_input.insert(pid_input.end(), ts_bytes.begin(), ts_bytes.end());
    Bytes pid_rsu = crypto_->compute_hash(pid_input);
    timer.stop("pid_gen");

    // Step 12-13: Session transcript → SessionID
    Bytes nonce_rsu = PacketSerializer::generate_nonce();

    Bytes transcript;
    transcript.insert(transcript.end(), req.pid_obu.begin(), req.pid_obu.end());
    transcript.insert(transcript.end(), pid_rsu.begin(), pid_rsu.end());
    transcript.insert(transcript.end(), req.nonce_obu.begin(), req.nonce_obu.end());
    transcript.insert(transcript.end(), nonce_rsu.begin(), nonce_rsu.end());
    for (int i = 7; i >= 0; --i)
        transcript.push_back(static_cast<uint8_t>((req.ts_obu >> (i * 8)) & 0xFF));
    for (int i = 7; i >= 0; --i)
        transcript.push_back(static_cast<uint8_t>((ts_rsu >> (i * 8)) & 0xFF));

    Bytes session_id = crypto_->compute_hash(transcript);
    std::string sid_hex = to_hex(session_id);
    std::cout << "[PROC] Step 13: SessionID = " << to_hex(session_id, 16) << std::endl;

    // Step 14-15: Derive session keys
    timer.start("derive_key");
    Bytes master_key = crypto_->derive_master_session_key(
        ss, req.nonce_obu, nonce_rsu, session_id);
    SessionKeys sk = crypto_->split_session_key(master_key);
    timer.stop("derive_key");
    std::cout << "[PROC] Step 15: Keys derived" << std::endl;

    // Create session entry
    SessionEntry entry;
    entry.session_id = session_id;
    entry.pid_obu = req.pid_obu;
    entry.pid_rsu = pid_rsu;
    entry.obu_ip = sender_ip;
    entry.obu_port = sender_port;
    entry.sk_enc = sk.sk_enc;
    entry.sk_mac = sk.sk_mac;
    entry.nonce_obu = req.nonce_obu;
    entry.nonce_rsu = nonce_rsu;
    entry.is_emergency = false;
    sessions_.create_session(entry);

    log_event("SESSION_CREATED", pid_hex, "RSU", sid_hex, "{}", timer);

    // Step 16: Send SessionID
    Bytes sid_packet = serializer_.serialize_session_id(session_id);
    udp_.send_to(std::vector<uint8_t>(sid_packet.begin(), sid_packet.end()),
                 sender_ip, sender_port);

    // Step 17-18: Construct and sign AuthResponse
    Bytes m2;
    m2.insert(m2.end(), pid_rsu.begin(), pid_rsu.end());
    m2.insert(m2.end(), keys_.pk_self.begin(), keys_.pk_self.end());
    for (int i = 7; i >= 0; --i)
        m2.push_back(static_cast<uint8_t>((ts_rsu >> (i * 8)) & 0xFF));
    m2.insert(m2.end(), nonce_rsu.begin(), nonce_rsu.end());
    m2.insert(m2.end(), req.nonce_obu.begin(), req.nonce_obu.end());

    timer.start("sign");
    Bytes sig_rsu = crypto_->sign(m2, keys_.sk);
    timer.stop("sign");

    // Step 19: Send AuthResponse
    AuthResponse resp;
    resp.pid_rsu = pid_rsu;
    resp.pk_rsu = keys_.pk_self;
    resp.ts_rsu = ts_rsu;
    resp.nonce_rsu = nonce_rsu;
    resp.nonce_obu = req.nonce_obu;
    resp.sig_rsu = sig_rsu;

    Bytes resp_packet = serializer_.serialize_auth_response(resp);
    udp_.send_to(std::vector<uint8_t>(resp_packet.begin(), resp_packet.end()),
                 sender_ip, sender_port);

    double total_us = timer.stop("total");
    std::cout << "[PROC] Step 19: AuthResponse sent (" << resp_packet.size()
              << " bytes, " << total_us / 1000.0 << " ms)" << std::endl;

    log_event("AUTH_RESPONSE_SENT", "RSU", pid_hex, sid_hex,
              "{\"response_size\":" + std::to_string(resp_packet.size()) +
              ",\"processing_ms\":" + std::to_string(total_us / 1000.0) + "}", timer);
}

// ============================================================================
// Handle KC1 (LLD Steps 27-30)
// ============================================================================

void PacketProcessor::handle_kc1(const Bytes& data,
                                  const std::string& sender_ip,
                                  int sender_port) {
    Timer timer;
    timer.start("total");

    std::cout << "[PROC] KC1 from " << sender_ip << ":" << sender_port << std::endl;

    if (data.size() < HEADER_SIZE + 32) {
        std::cout << "[PROC] KC1 too small (" << data.size() << " bytes), ignoring" << std::endl;
        return;
    }

    // Find the session for this sender
    SessionEntry* session = sessions_.find_by_address(sender_ip, sender_port);
    if (!session) {
        std::cout << "[PROC] ✗ No session found for " << sender_ip
                  << ":" << sender_port << std::endl;
        log_event("KC1_NO_SESSION", sender_ip, "RSU", "", "{}", timer);
        return;
    }

    Bytes recv_kc1 = serializer_.deserialize_kc(data);
    std::string sid_hex = to_hex(session->session_id);
    log_event("KC1_RECEIVED", to_hex(session->pid_obu, 16), "RSU", sid_hex, "{}", timer);

    // Step 27: Compute expected KC1
    timer.start("hmac");
    Bytes kc1_input;
    std::string kc1_tag = "KC1";
    kc1_input.insert(kc1_input.end(), kc1_tag.begin(), kc1_tag.end());
    kc1_input.insert(kc1_input.end(), session->session_id.begin(), session->session_id.end());
    kc1_input.insert(kc1_input.end(), session->nonce_obu.begin(), session->nonce_obu.end());
    kc1_input.insert(kc1_input.end(), session->nonce_rsu.begin(), session->nonce_rsu.end());

    Bytes expected_kc1 = crypto_->compute_hmac(session->sk_mac, kc1_input);
    timer.stop("hmac");

    // Step 28: Verify
    if (recv_kc1 != expected_kc1) {
        std::cout << "[PROC] ✗ KC1 MISMATCH" << std::endl;
        sessions_.set_state(session->pid_obu, SessionState::ABORTED);
        log_event("KC1_VERIFY_FAIL", to_hex(session->pid_obu, 16), "RSU", sid_hex, "{}", timer);
        return;
    }
    std::cout << "[PROC] Step 28: KC1 VALID ✓" << std::endl;
    log_event("KC1_VERIFY_PASS", to_hex(session->pid_obu, 16), "RSU", sid_hex, "{}", timer);

    // Step 29: Compute KC2 (note reversed nonce order)
    Bytes kc2_input;
    std::string kc2_tag = "KC2";
    kc2_input.insert(kc2_input.end(), kc2_tag.begin(), kc2_tag.end());
    kc2_input.insert(kc2_input.end(), session->session_id.begin(), session->session_id.end());
    kc2_input.insert(kc2_input.end(), session->nonce_rsu.begin(), session->nonce_rsu.end());
    kc2_input.insert(kc2_input.end(), session->nonce_obu.begin(), session->nonce_obu.end());

    Bytes kc2 = crypto_->compute_hmac(session->sk_mac, kc2_input);

    // Step 30: Send KC2
    Bytes kc2_packet = serializer_.serialize_kc(PKT_KC2, kc2);
    udp_.send_to(std::vector<uint8_t>(kc2_packet.begin(), kc2_packet.end()),
                 sender_ip, sender_port);

    sessions_.set_state(session->pid_obu, SessionState::ACTIVE);

    double total_us = timer.stop("total");

    // Compute full auth latency: from session creation (AuthRequest processing) to now
    auto now = std::chrono::steady_clock::now();
    double full_latency_ms = std::chrono::duration_cast<std::chrono::microseconds>(
        now - session->created_at).count() / 1000.0;

    std::cout << "[PROC] Step 30: KC2 sent. SESSION ESTABLISHED ✓ ("
              << full_latency_ms << " ms total)" << std::endl;

    std::string details = "{\"total_latency_ms\":" + std::to_string(full_latency_ms) +
                          ",\"kc_processing_ms\":" + std::to_string(total_us / 1000.0) + "}";
    log_event("SESSION_ESTABLISHED", to_hex(session->pid_obu, 16), "RSU",
              sid_hex, details, timer);
}

// ============================================================================
// Handle Post-Auth Message
// ============================================================================

void PacketProcessor::handle_post_auth(const Bytes& data,
                                        const std::string& sender_ip,
                                        int sender_port) {
    Timer timer;
    timer.start("total");
    std::cout << "[PROC] Post-auth message from " << sender_ip << ":" << sender_port << std::endl;

    // HEADER_SIZE + 4 (enc_len field) + 1 (min payload) + 32 (HMAC)
    if (data.size() < HEADER_SIZE + 4 + 1 + 32) {
        std::cout << "[PROC] Post-auth too small (" << data.size() << " bytes), ignoring" << std::endl;
        return;
    }

    SessionEntry* session = sessions_.find_active_by_address(sender_ip, sender_port);
    if (!session) {
        std::cout << "[PROC] ✗ No active session for post-auth" << std::endl;
        return;
    }

    PostAuthMessage msg = serializer_.deserialize_post_auth(data);

    // Step 1: Verify HMAC(sk_mac, encrypted_payload)
    timer.start("hmac_verify");
    Bytes expected_hmac = crypto_->compute_hmac(session->sk_mac, msg.encrypted_payload);
    timer.stop("hmac_verify");

    if (msg.hmac_tag != expected_hmac) {
        std::cout << "[PROC] ✗ Post-auth HMAC invalid" << std::endl;
        std::string sid_hex = to_hex(session->session_id);
        log_event("POST_AUTH_HMAC_FAIL", to_hex(session->pid_obu, 16), "RSU",
                  sid_hex, "{}", timer);
        return;
    }
    std::cout << "[PROC] Post-auth HMAC verified ✓" << std::endl;

    // Step 2: Decrypt with AES-GCM(sk_enc)
    timer.start("aes_decrypt");
    Bytes plaintext;
    try {
        plaintext = crypto_->aes_gcm_decrypt(session->sk_enc, msg.encrypted_payload);
    } catch (const std::exception& e) {
        timer.stop("aes_decrypt");
        std::cout << "[PROC] ✗ Post-auth decryption failed: " << e.what() << std::endl;
        std::string sid_hex = to_hex(session->session_id);
        log_event("POST_AUTH_DECRYPT_FAIL", to_hex(session->pid_obu, 16), "RSU",
                  sid_hex, "{}", timer);
        return;
    }
    timer.stop("aes_decrypt");

    std::string payload_str(plaintext.begin(), plaintext.end());

    // Step 3: Check for emergency flag
    std::string sid_hex = to_hex(session->session_id);
    bool is_emergency = (payload_str.find("\"is_emergency\":true") != std::string::npos);

    if (is_emergency) {
        if (!session->is_emergency) {
            // First emergency heartbeat for this session — log once and print
            std::cout << "[PROC] 🚑 EMERGENCY VEHICLE DETECTED — Granting priority" << std::endl;
            session->is_emergency = true;
            log_event("EMERGENCY_PRIORITY_GRANTED", to_hex(session->pid_obu, 16), "RSU",
                      sid_hex,
                      "{\"payload_size\":" + std::to_string(plaintext.size()) + ",\"emergency\":true}",
                      timer);
        }
        // Always notify car — keeps car emergency active even after a car restart
        send_car_alert(true, sid_hex);
    } else {
        log_event("POST_AUTH_RECEIVED", to_hex(session->pid_obu, 16), "RSU",
                  sid_hex,
                  "{\"payload_size\":" + std::to_string(plaintext.size()) + ",\"emergency\":false}",
                  timer);
    }

    timer.stop("total");
}

// ============================================================================
// Logging Helper
// ============================================================================

void PacketProcessor::log_event(const std::string& event_type,
                                 const std::string& source,
                                 const std::string& target,
                                 const std::string& session_id_hex,
                                 const std::string& details_json,
                                 const Timer& timer) {
    // Get current ISO timestamp
    auto now = std::chrono::system_clock::now();
    auto time_t = std::chrono::system_clock::to_time_t(now);
    auto us = std::chrono::duration_cast<std::chrono::microseconds>(
        now.time_since_epoch()).count() % 1000000;
    char ts_buf[64];
    struct tm tm;
    gmtime_r(&time_t, &tm);
    strftime(ts_buf, sizeof(ts_buf), "%Y-%m-%dT%H:%M:%S", &tm);

    std::ostringstream ts;
    ts << ts_buf << "." << std::setfill('0') << std::setw(6) << us;

    // Build timing JSON
    std::ostringstream timing_json;
    timing_json << "{";
    bool first = true;
    for (auto& [op, us_val] : timer.all_results()) {
        if (op == "total") continue;
        if (!first) timing_json << ",";
        timing_json << "\"" << op << "_ms\":" << (us_val / 1000.0);
        first = false;
    }
    timing_json << "}";

    // Build full event JSON
    std::ostringstream json;
    json << "{"
         << "\"timestamp\":\"" << ts.str() << "\","
         << "\"event_type\":\"" << event_type << "\","
         << "\"source\":\"" << source << "\","
         << "\"target\":\"" << target << "\","
         << "\"session_id\":\"" << session_id_hex << "\","
         << "\"details\":" << details_json << ","
         << "\"crypto_timing\":" << timing_json.str() << ","
         << "\"crypto_provider\":\"" << crypto_->get_provider_name() << "\""
         << "}";

    logger_.send_event(json.str());
}

} // namespace v2x
