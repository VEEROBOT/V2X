/**
 * File: test_protocol_flow.cpp
 * Module: V2X Authentication Testbed - Full Protocol Flow Test
 *
 * Purpose:
 *    Simulates the complete 32-step authentication between OBU and RSU
 *    entirely in memory (no network). Validates the entire crypto chain
 *    including post-authentication AES-GCM encrypted messaging.
 *
 * Author(s): Praveen Kumar
 * Company: Siliris Technologies Pvt. Ltd
 * Created: 15th February 2026
 * Version: 1.2
 *
 * License:
 *    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
 *    Proprietary - See LICENSE file for terms and conditions.
 */

#include "crypto/placeholder_provider.h"
#include "packets/packet_serializer.h"
#include "common/timer.h"
#include "utils/hex_utils.h"
#include <iostream>
#include <cassert>
#include <string>

using namespace v2x;

int main() {
    std::cout << "========================================\n";
    std::cout << "  Full Protocol Flow Test\n";
    std::cout << "  (32-step auth + post-auth messaging)\n";
    std::cout << "========================================\n\n";

    PlaceholderProvider crypto;
    PacketSerializer ser(&crypto);
    Timer timer;

    // =====================================================================
    // SETUP: Registration (pre-provisioned keys)
    // =====================================================================

    std::cout << "  [SETUP] Generating keypairs...\n";
    KeyPair obu_kp = crypto.generate_keypair();
    KeyPair rsu_kp = crypto.generate_keypair();

    Bytes master_secret(32, 0x42);
    Bytes obu_id = {0x4F, 0x42, 0x55, 0x31}; // "OBU1"
    obu_id.resize(32, 0);
    Bytes rsu_id = {0x52, 0x53, 0x55, 0x00};
    rsu_id.resize(32, 0);

    // =====================================================================
    // STEP 1-6: OBU constructs and sends AuthRequest
    // =====================================================================

    timer.start("total_auth");
    std::cout << "\n  --- OBU Side ---\n";

    timer.start("pid_gen");
    Bytes ts_bytes(8);
    int64_t pid_ts = PacketSerializer::now_microseconds();
    for (int i = 7; i >= 0; --i) ts_bytes[7-i] = (pid_ts >> (i*8)) & 0xFF;
    Bytes pid_input;
    pid_input.insert(pid_input.end(), obu_id.begin(), obu_id.end());
    pid_input.insert(pid_input.end(), master_secret.begin(), master_secret.end());
    pid_input.insert(pid_input.end(), ts_bytes.begin(), ts_bytes.end());
    Bytes pid_obu = crypto.compute_hash(pid_input);
    timer.stop("pid_gen");
    std::cout << "  Step 1:  PID_OBU = " << to_hex(pid_obu, 16) << "\n";

    timer.start("encapsulate");
    KEMResult kem = crypto.encapsulate(rsu_kp.public_key);
    timer.stop("encapsulate");
    Bytes ss_obu = kem.shared_secret;
    std::cout << "  Step 2-3: Encapsulated. ct=" << kem.ciphertext.size()
              << "B, ss=" << to_hex(ss_obu, 8) << "\n";

    int64_t ts_obu = PacketSerializer::now_microseconds();
    Bytes nonce_obu = PacketSerializer::generate_nonce();

    Bytes m1;
    m1.insert(m1.end(), pid_obu.begin(), pid_obu.end());
    m1.insert(m1.end(), obu_kp.public_key.begin(), obu_kp.public_key.end());
    m1.insert(m1.end(), kem.ciphertext.begin(), kem.ciphertext.end());
    for (int i = 7; i >= 0; --i) m1.push_back((ts_obu >> (i*8)) & 0xFF);
    m1.insert(m1.end(), nonce_obu.begin(), nonce_obu.end());

    timer.start("sign_obu");
    Bytes sig_obu = crypto.sign(m1, obu_kp.private_key);
    timer.stop("sign_obu");
    std::cout << "  Step 5:  Signed. sig=" << sig_obu.size() << "B\n";

    AuthRequest auth_req;
    auth_req.pid_obu = pid_obu;
    auth_req.pk_obu = obu_kp.public_key;
    auth_req.ct_obu = kem.ciphertext;
    auth_req.ts_obu = ts_obu;
    auth_req.nonce_obu = nonce_obu;
    auth_req.sig_obu = sig_obu;
    Bytes auth_req_packet = ser.serialize_auth_request(auth_req);
    std::cout << "  Step 6:  AuthRequest = " << auth_req_packet.size() << " bytes\n";

    // =====================================================================
    // STEP 7-19: RSU processes AuthRequest and sends AuthResponse
    // =====================================================================

    std::cout << "\n  --- RSU Side ---\n";

    AuthRequest recv_req = ser.deserialize_auth_request(auth_req_packet);
    int64_t ts_rsu_recv = PacketSerializer::now_microseconds();
    std::cout << "  Step 7:  Received AuthRequest\n";

    int64_t ts_diff = std::abs(recv_req.ts_obu - ts_rsu_recv);
    int64_t delta_ts = 50000;
    assert(ts_diff <= delta_ts);
    std::cout << "  Step 8:  Timestamp OK (diff=" << ts_diff << "us)\n";

    Bytes m1_reconstructed;
    m1_reconstructed.insert(m1_reconstructed.end(), recv_req.pid_obu.begin(), recv_req.pid_obu.end());
    m1_reconstructed.insert(m1_reconstructed.end(), recv_req.pk_obu.begin(), recv_req.pk_obu.end());
    m1_reconstructed.insert(m1_reconstructed.end(), recv_req.ct_obu.begin(), recv_req.ct_obu.end());
    for (int i = 7; i >= 0; --i) m1_reconstructed.push_back((recv_req.ts_obu >> (i*8)) & 0xFF);
    m1_reconstructed.insert(m1_reconstructed.end(), recv_req.nonce_obu.begin(), recv_req.nonce_obu.end());

    timer.start("verify_sig_rsu");
    bool sig_valid = crypto.verify_signature(recv_req.sig_obu, m1_reconstructed, recv_req.pk_obu);
    timer.stop("verify_sig_rsu");
    assert(sig_valid);
    std::cout << "  Step 9:  Signature VALID\n";

    timer.start("decapsulate");
    Bytes ss_rsu = crypto.decapsulate(recv_req.ct_obu, rsu_kp.private_key);
    timer.stop("decapsulate");
    assert(ss_rsu == ss_obu);
    std::cout << "  Step 10: Decapsulated. ss=" << to_hex(ss_rsu, 8) << "\n";

    Bytes pid_rsu = crypto.compute_hash(rsu_id);
    Bytes nonce_rsu = PacketSerializer::generate_nonce();
    int64_t ts_rsu = PacketSerializer::now_microseconds();

    Bytes transcript;
    transcript.insert(transcript.end(), pid_obu.begin(), pid_obu.end());
    transcript.insert(transcript.end(), pid_rsu.begin(), pid_rsu.end());
    transcript.insert(transcript.end(), nonce_obu.begin(), nonce_obu.end());
    transcript.insert(transcript.end(), nonce_rsu.begin(), nonce_rsu.end());
    for (int i = 7; i >= 0; --i) transcript.push_back((ts_obu >> (i*8)) & 0xFF);
    for (int i = 7; i >= 0; --i) transcript.push_back((ts_rsu >> (i*8)) & 0xFF);

    Bytes session_id = crypto.compute_hash(transcript);
    std::cout << "  Step 13: SessionID = " << to_hex(session_id, 16) << "\n";

    timer.start("derive_key_rsu");
    Bytes mk_rsu = crypto.derive_master_session_key(ss_rsu, nonce_obu, nonce_rsu, session_id);
    timer.stop("derive_key_rsu");
    SessionKeys keys_rsu = crypto.split_session_key(mk_rsu);

    Bytes m2;
    m2.insert(m2.end(), pid_rsu.begin(), pid_rsu.end());
    m2.insert(m2.end(), rsu_kp.public_key.begin(), rsu_kp.public_key.end());
    for (int i = 7; i >= 0; --i) m2.push_back((ts_rsu >> (i*8)) & 0xFF);
    m2.insert(m2.end(), nonce_rsu.begin(), nonce_rsu.end());
    m2.insert(m2.end(), nonce_obu.begin(), nonce_obu.end());

    timer.start("sign_rsu");
    Bytes sig_rsu = crypto.sign(m2, rsu_kp.private_key);
    timer.stop("sign_rsu");

    AuthResponse auth_resp;
    auth_resp.pid_rsu = pid_rsu;
    auth_resp.pk_rsu = rsu_kp.public_key;
    auth_resp.ts_rsu = ts_rsu;
    auth_resp.nonce_rsu = nonce_rsu;
    auth_resp.nonce_obu = nonce_obu;
    auth_resp.sig_rsu = sig_rsu;

    Bytes sid_packet = ser.serialize_session_id(session_id);
    Bytes resp_packet = ser.serialize_auth_response(auth_resp);
    std::cout << "  Step 19: AuthResponse = " << resp_packet.size() << " bytes\n";

    // =====================================================================
    // STEP 20-26: OBU processes response, sends KC1
    // =====================================================================

    std::cout << "\n  --- OBU Side (Response) ---\n";

    Bytes recv_sid = ser.deserialize_session_id(sid_packet);
    AuthResponse recv_resp = ser.deserialize_auth_response(resp_packet);

    timer.start("verify_sig_obu");
    Bytes m2_check;
    m2_check.insert(m2_check.end(), recv_resp.pid_rsu.begin(), recv_resp.pid_rsu.end());
    m2_check.insert(m2_check.end(), recv_resp.pk_rsu.begin(), recv_resp.pk_rsu.end());
    for (int i = 7; i >= 0; --i) m2_check.push_back((recv_resp.ts_rsu >> (i*8)) & 0xFF);
    m2_check.insert(m2_check.end(), recv_resp.nonce_rsu.begin(), recv_resp.nonce_rsu.end());
    m2_check.insert(m2_check.end(), recv_resp.nonce_obu.begin(), recv_resp.nonce_obu.end());

    bool rsu_sig_valid = crypto.verify_signature(recv_resp.sig_rsu, m2_check, recv_resp.pk_rsu);
    timer.stop("verify_sig_obu");
    assert(rsu_sig_valid);
    std::cout << "  Step 22: RSU signature VALID\n";

    Bytes mk_obu = crypto.derive_master_session_key(ss_obu, nonce_obu, recv_resp.nonce_rsu, recv_sid);
    SessionKeys keys_obu = crypto.split_session_key(mk_obu);
    assert(keys_obu.sk_enc == keys_rsu.sk_enc);
    assert(keys_obu.sk_mac == keys_rsu.sk_mac);
    std::cout << "  Step 24: Keys match RSU\n";

    Bytes kc1_input;
    std::string kc1_tag = "KC1";
    kc1_input.insert(kc1_input.end(), kc1_tag.begin(), kc1_tag.end());
    kc1_input.insert(kc1_input.end(), session_id.begin(), session_id.end());
    kc1_input.insert(kc1_input.end(), nonce_obu.begin(), nonce_obu.end());
    kc1_input.insert(kc1_input.end(), recv_resp.nonce_rsu.begin(), recv_resp.nonce_rsu.end());

    Bytes kc1 = crypto.compute_hmac(keys_obu.sk_mac, kc1_input);
    Bytes kc1_packet = ser.serialize_kc(PKT_KC1, kc1);

    // =====================================================================
    // STEP 27-30: RSU verifies KC1, sends KC2
    // =====================================================================

    std::cout << "\n  --- RSU Side (KC) ---\n";

    Bytes recv_kc1 = ser.deserialize_kc(kc1_packet);
    Bytes expected_kc1 = crypto.compute_hmac(keys_rsu.sk_mac, kc1_input);
    assert(recv_kc1 == expected_kc1);
    std::cout << "  Step 28: KC1 VALID\n";

    Bytes kc2_input;
    std::string kc2_tag = "KC2";
    kc2_input.insert(kc2_input.end(), kc2_tag.begin(), kc2_tag.end());
    kc2_input.insert(kc2_input.end(), session_id.begin(), session_id.end());
    kc2_input.insert(kc2_input.end(), nonce_rsu.begin(), nonce_rsu.end());
    kc2_input.insert(kc2_input.end(), nonce_obu.begin(), nonce_obu.end());

    Bytes kc2 = crypto.compute_hmac(keys_rsu.sk_mac, kc2_input);
    Bytes kc2_packet = ser.serialize_kc(PKT_KC2, kc2);

    // =====================================================================
    // STEP 31-32: OBU verifies KC2 - SESSION ESTABLISHED
    // =====================================================================

    std::cout << "\n  --- OBU Side (Final) ---\n";

    Bytes recv_kc2 = ser.deserialize_kc(kc2_packet);
    Bytes expected_kc2 = crypto.compute_hmac(keys_obu.sk_mac, kc2_input);
    assert(recv_kc2 == expected_kc2);
    double total_us = timer.stop("total_auth");
    std::cout << "  Step 32: KC2 VALID\n";

    std::cout << "\n  SESSION ESTABLISHED SUCCESSFULLY\n";
    std::cout << "  SessionID: " << to_hex(session_id, 16) << "...\n";
    std::cout << "  Total time: " << total_us / 1000.0 << " ms\n";

    // =====================================================================
    // POST-AUTH: AES-GCM encrypted messaging test
    // =====================================================================

    std::cout << "\n  --- Post-Auth Messaging ---\n";

    std::string payload_str = "{\"entity_id\":\"OBU1\",\"is_emergency\":true,\"message\":\"V2X_STATUS_OK\"}";
    Bytes plaintext(payload_str.begin(), payload_str.end());

    timer.start("aes_gcm_encrypt");
    Bytes encrypted = crypto.aes_gcm_encrypt(keys_obu.sk_enc, plaintext);
    timer.stop("aes_gcm_encrypt");
    std::cout << "  AES-GCM encrypt: " << plaintext.size() << "B -> " << encrypted.size() << "B\n";

    Bytes hmac = crypto.compute_hmac(keys_obu.sk_mac, encrypted);
    Bytes post_auth_packet = ser.serialize_post_auth(encrypted, hmac);
    std::cout << "  Post-auth packet: " << post_auth_packet.size() << " bytes on wire\n";

    PostAuthMessage recv_msg = ser.deserialize_post_auth(post_auth_packet);

    Bytes expected_hmac = crypto.compute_hmac(keys_rsu.sk_mac, recv_msg.encrypted_payload);
    assert(recv_msg.hmac_tag == expected_hmac);
    std::cout << "  HMAC verified\n";

    timer.start("aes_gcm_decrypt");
    Bytes decrypted = crypto.aes_gcm_decrypt(keys_rsu.sk_enc, recv_msg.encrypted_payload);
    timer.stop("aes_gcm_decrypt");
    assert(decrypted == plaintext);
    std::string decrypted_str(decrypted.begin(), decrypted.end());
    std::cout << "  AES-GCM decrypt: " << decrypted.size() << "B recovered\n";
    std::cout << "  Payload: " << decrypted_str << "\n";

    bool is_emergency = (decrypted_str.find("\"is_emergency\":true") != std::string::npos);
    assert(is_emergency);
    std::cout << "  Emergency flag: DETECTED\n";

    // Tamper detection
    std::cout << "\n  --- Security Tests ---\n";
    Bytes tampered = encrypted;
    tampered[20] ^= 0xFF;
    bool tamper_caught = false;
    try {
        crypto.aes_gcm_decrypt(keys_rsu.sk_enc, tampered);
    } catch (const std::runtime_error&) {
        tamper_caught = true;
    }
    assert(tamper_caught);
    std::cout << "  Tampered data rejected\n";

    Bytes wrong_key(32, 0xFF);
    bool wrong_key_caught = false;
    try {
        crypto.aes_gcm_decrypt(wrong_key, encrypted);
    } catch (const std::runtime_error&) {
        wrong_key_caught = true;
    }
    assert(wrong_key_caught);
    std::cout << "  Wrong key rejected\n";

    // Timing
    std::cout << "\n  Timing Breakdown:\n";
    for (auto& [op, us] : timer.all_results()) {
        if (op != "total_auth")
            printf("    %-20s %8.1f us  (%6.3f ms)\n", op.c_str(), us, us / 1000.0);
    }

    std::cout << "\n========================================\n";
    std::cout << "  PASSED: 32-step protocol flow\n";
    std::cout << "  PASSED: Post-auth AES-GCM messaging\n";
    std::cout << "  PASSED: Tamper detection\n";
    std::cout << "  PASSED: Wrong key rejection\n";
    std::cout << "========================================\n";

    return 0;
}
