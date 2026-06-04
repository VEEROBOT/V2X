/**
 * Test: Packet Serializer
 * Validates: serialize → deserialize roundtrip for all packet types
 */

#include "crypto/placeholder_provider.h"
#include "packets/packet_serializer.h"
#include "utils/hex_utils.h"
#include <iostream>
#include <cassert>

using namespace v2x;

static int tests_passed = 0;
static int tests_failed = 0;

#define TEST(name) std::cout << "  TEST: " << name << "... ";
#define PASS() { std::cout << "✓ PASS\n"; tests_passed++; }
#define FAIL(msg) { std::cout << "✗ FAIL: " << msg << "\n"; tests_failed++; }

int main() {
    std::cout << "========================================\n";
    std::cout << "  Packet Serializer Tests\n";
    std::cout << "========================================\n";

    PlaceholderProvider crypto;
    PacketSerializer ser(&crypto);

    // ---- AuthRequest ----
    TEST("AuthRequest serialize/deserialize roundtrip")
    {
        KeyPair obu_kp = crypto.generate_keypair();
        KeyPair rsu_kp = crypto.generate_keypair();
        KEMResult kem = crypto.encapsulate(rsu_kp.public_key);

        Bytes pid(32, 0xAA);
        Bytes nonce = PacketSerializer::generate_nonce();
        int64_t ts = PacketSerializer::now_microseconds();

        // Build message for signing
        Bytes msg;
        msg.insert(msg.end(), pid.begin(), pid.end());
        msg.insert(msg.end(), obu_kp.public_key.begin(), obu_kp.public_key.end());
        msg.insert(msg.end(), kem.ciphertext.begin(), kem.ciphertext.end());
        // Add timestamp bytes
        for (int i = 7; i >= 0; --i)
            msg.push_back(static_cast<uint8_t>((ts >> (i * 8)) & 0xFF));
        msg.insert(msg.end(), nonce.begin(), nonce.end());

        Bytes sig = crypto.sign(msg, obu_kp.private_key);

        AuthRequest req;
        req.pid_obu = pid;
        req.pk_obu = obu_kp.public_key;
        req.ct_obu = kem.ciphertext;
        req.ts_obu = ts;
        req.nonce_obu = nonce;
        req.sig_obu = sig;

        Bytes packet = ser.serialize_auth_request(req);
        AuthRequest req2 = ser.deserialize_auth_request(packet);

        bool ok = (req2.pid_obu == req.pid_obu &&
                   req2.pk_obu == req.pk_obu &&
                   req2.ct_obu == req.ct_obu &&
                   req2.ts_obu == req.ts_obu &&
                   req2.nonce_obu == req.nonce_obu &&
                   req2.sig_obu == req.sig_obu);
        if (ok) PASS() else FAIL("fields mismatch")
    }

    TEST("AuthRequest packet size matches expected")
    {
        size_t expected = ser.get_auth_request_size();
        // Build a minimal packet to check size
        AuthRequest req;
        req.pid_obu.resize(32, 0);
        req.pk_obu.resize(crypto.get_public_key_size(), 0);
        req.ct_obu.resize(crypto.get_ct_size(), 0);
        req.ts_obu = 0;
        req.nonce_obu.resize(32, 0);
        req.sig_obu.resize(crypto.get_signature_size(), 0);
        Bytes packet = ser.serialize_auth_request(req);
        if (packet.size() == expected) PASS()
        else FAIL("got=" + std::to_string(packet.size())
                   + " expected=" + std::to_string(expected))
    }

    // ---- AuthResponse ----
    TEST("AuthResponse serialize/deserialize roundtrip")
    {
        KeyPair rsu_kp = crypto.generate_keypair();
        Bytes pid(32, 0xBB);
        Bytes nonce_rsu = PacketSerializer::generate_nonce();
        Bytes nonce_obu = PacketSerializer::generate_nonce();
        int64_t ts = PacketSerializer::now_microseconds();

        Bytes msg;
        msg.insert(msg.end(), pid.begin(), pid.end());
        Bytes sig = crypto.sign(msg, rsu_kp.private_key);

        AuthResponse resp;
        resp.pid_rsu = pid;
        resp.pk_rsu = rsu_kp.public_key;
        resp.ts_rsu = ts;
        resp.nonce_rsu = nonce_rsu;
        resp.nonce_obu = nonce_obu;
        resp.sig_rsu = sig;

        Bytes packet = ser.serialize_auth_response(resp);
        AuthResponse resp2 = ser.deserialize_auth_response(packet);

        bool ok = (resp2.pid_rsu == resp.pid_rsu &&
                   resp2.pk_rsu == resp.pk_rsu &&
                   resp2.ts_rsu == resp.ts_rsu &&
                   resp2.nonce_rsu == resp.nonce_rsu &&
                   resp2.nonce_obu == resp.nonce_obu &&
                   resp2.sig_rsu == resp.sig_rsu);
        if (ok) PASS() else FAIL("fields mismatch")
    }

    // ---- SessionID ----
    TEST("SessionID serialize/deserialize")
    {
        Bytes sid(32, 0xCC);
        Bytes packet = ser.serialize_session_id(sid);
        Bytes sid2 = ser.deserialize_session_id(packet);
        if (sid == sid2) PASS() else FAIL("session IDs differ")
    }

    // ---- KC1/KC2 ----
    TEST("KC1 serialize/deserialize")
    {
        Bytes kc(32, 0xDD);
        Bytes packet = ser.serialize_kc(PKT_KC1, kc);
        Bytes kc2 = ser.deserialize_kc(packet);
        if (kc == kc2) PASS() else FAIL("KC values differ")
    }

    TEST("KC2 serialize/deserialize")
    {
        Bytes kc(32, 0xEE);
        Bytes packet = ser.serialize_kc(PKT_KC2, kc);
        PacketHeader hdr = ser.deserialize_header(packet);
        if (hdr.type == PKT_KC2) PASS() else FAIL("wrong type")
    }

    // ---- PostAuth ----
    TEST("PostAuth message serialize/deserialize")
    {
        Bytes encrypted = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10};
        Bytes hmac(32, 0xFF);
        Bytes packet = ser.serialize_post_auth(encrypted, hmac);
        PostAuthMessage msg = ser.deserialize_post_auth(packet);
        bool ok = (msg.encrypted_payload == encrypted && msg.hmac_tag == hmac);
        if (ok) PASS() else FAIL("payload mismatch")
    }

    // ---- Header ----
    TEST("Header parsing")
    {
        Bytes sid(32, 0);
        Bytes packet = ser.serialize_session_id(sid);
        PacketHeader hdr = ser.deserialize_header(packet);
        if (hdr.type == PKT_SESSION_ID) PASS() else FAIL("wrong type")
    }

    // ---- Packet sizes ----
    std::cout << "\n  Packet Sizes (placeholder):\n";
    std::cout << "    AuthRequest:  " << ser.get_auth_request_size() << " bytes\n";
    std::cout << "    AuthResponse: " << ser.get_auth_response_size() << " bytes\n";
    std::cout << "    SessionID:    " << (HEADER_SIZE + 32) << " bytes\n";
    std::cout << "    KC1/KC2:      " << (HEADER_SIZE + 32) << " bytes\n";

    // ---- Summary ----
    std::cout << "\n========================================\n";
    std::cout << "  Results: " << tests_passed << " passed, "
              << tests_failed << " failed\n";
    std::cout << "========================================\n";

    return tests_failed > 0 ? 1 : 0;
}
