/**
 * Test: Crypto Provider (PlaceholderProvider)
 * Validates: hash, hmac, sign/verify, encap/decap, key derivation
 */

#include "crypto/placeholder_provider.h"
#include "utils/hex_utils.h"
#include "common/timer.h"
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
    std::cout << "  Crypto Provider Tests\n";
    std::cout << "========================================\n";

    PlaceholderProvider crypto;
    Timer timer;

    // ---- Hash ----
    TEST("Hash produces 32 bytes")
    {
        Bytes data = {1, 2, 3, 4, 5};
        timer.start("hash");
        Bytes hash = crypto.compute_hash(data);
        timer.stop("hash");
        if (hash.size() == 32) PASS() else FAIL("size=" + std::to_string(hash.size()))
    }

    TEST("Hash is deterministic")
    {
        Bytes data = {10, 20, 30};
        Bytes h1 = crypto.compute_hash(data);
        Bytes h2 = crypto.compute_hash(data);
        if (h1 == h2) PASS() else FAIL("hashes differ")
    }

    TEST("Hash differs for different inputs")
    {
        Bytes h1 = crypto.compute_hash({1, 2, 3});
        Bytes h2 = crypto.compute_hash({4, 5, 6});
        if (h1 != h2) PASS() else FAIL("hashes are the same")
    }

    // ---- HMAC ----
    TEST("HMAC produces 32 bytes")
    {
        Bytes key(32, 0xAB);
        Bytes data = {1, 2, 3};
        timer.start("hmac");
        Bytes mac = crypto.compute_hmac(key, data);
        timer.stop("hmac");
        if (mac.size() == 32) PASS() else FAIL("size=" + std::to_string(mac.size()))
    }

    TEST("HMAC is deterministic")
    {
        Bytes key(32, 0xCD);
        Bytes data = {7, 8, 9};
        Bytes m1 = crypto.compute_hmac(key, data);
        Bytes m2 = crypto.compute_hmac(key, data);
        if (m1 == m2) PASS() else FAIL("HMACs differ")
    }

    // ---- Keypair ----
    TEST("Generate keypair")
    {
        timer.start("keygen");
        KeyPair kp = crypto.generate_keypair();
        timer.stop("keygen");
        bool ok = (kp.public_key.size() == 65 && kp.private_key.size() == 32);
        if (ok) PASS() else FAIL("PK=" + std::to_string(kp.public_key.size())
                                  + " SK=" + std::to_string(kp.private_key.size()))
    }

    TEST("Two keypairs are different")
    {
        KeyPair kp1 = crypto.generate_keypair();
        KeyPair kp2 = crypto.generate_keypair();
        if (kp1.public_key != kp2.public_key) PASS() else FAIL("same keys")
    }

    // ---- Sign / Verify ----
    TEST("Sign and verify roundtrip")
    {
        KeyPair kp = crypto.generate_keypair();
        Bytes message = {0xDE, 0xAD, 0xBE, 0xEF, 0x01, 0x02, 0x03};

        timer.start("sign");
        Bytes sig = crypto.sign(message, kp.private_key);
        timer.stop("sign");

        timer.start("verify");
        bool valid = crypto.verify_signature(sig, message, kp.public_key);
        timer.stop("verify");

        if (valid) PASS() else FAIL("signature invalid")
    }

    TEST("Verify rejects wrong message")
    {
        KeyPair kp = crypto.generate_keypair();
        Bytes msg1 = {1, 2, 3};
        Bytes msg2 = {4, 5, 6};
        Bytes sig = crypto.sign(msg1, kp.private_key);
        bool valid = crypto.verify_signature(sig, msg2, kp.public_key);
        if (!valid) PASS() else FAIL("accepted wrong message")
    }

    TEST("Verify rejects wrong key")
    {
        KeyPair kp1 = crypto.generate_keypair();
        KeyPair kp2 = crypto.generate_keypair();
        Bytes message = {1, 2, 3};
        Bytes sig = crypto.sign(message, kp1.private_key);
        bool valid = crypto.verify_signature(sig, message, kp2.public_key);
        if (!valid) PASS() else FAIL("accepted wrong key")
    }

    // ---- KEM (Encapsulate / Decapsulate) ----
    TEST("KEM encap/decap produces same shared secret")
    {
        KeyPair recipient = crypto.generate_keypair();

        timer.start("encapsulate");
        KEMResult kem = crypto.encapsulate(recipient.public_key);
        timer.stop("encapsulate");

        timer.start("decapsulate");
        Bytes ss_decap = crypto.decapsulate(kem.ciphertext, recipient.private_key);
        timer.stop("decapsulate");

        if (kem.shared_secret == ss_decap) PASS()
        else FAIL("shared secrets differ:\n    encap=" + to_hex(kem.shared_secret, 16)
                   + "\n    decap=" + to_hex(ss_decap, 16))
    }

    TEST("KEM ciphertext is correct size")
    {
        KeyPair kp = crypto.generate_keypair();
        KEMResult kem = crypto.encapsulate(kp.public_key);
        if (kem.ciphertext.size() == crypto.get_ct_size()) PASS()
        else FAIL("ct size=" + std::to_string(kem.ciphertext.size()))
    }

    TEST("KEM shared secret is 32 bytes")
    {
        KeyPair kp = crypto.generate_keypair();
        KEMResult kem = crypto.encapsulate(kp.public_key);
        if (kem.shared_secret.size() == 32) PASS()
        else FAIL("ss size=" + std::to_string(kem.shared_secret.size()))
    }

    // ---- Session Key Derivation ----
    TEST("Derive master session key (64 bytes)")
    {
        Bytes ss(32, 0x42);
        Bytes nonce_obu(32, 0xAA);
        Bytes nonce_rsu(32, 0xBB);
        Bytes session_id(32, 0xCC);

        timer.start("derive_key");
        Bytes mk = crypto.derive_master_session_key(ss, nonce_obu, nonce_rsu, session_id);
        timer.stop("derive_key");

        if (mk.size() == 64) PASS() else FAIL("size=" + std::to_string(mk.size()))
    }

    TEST("Split session key into enc + mac")
    {
        Bytes mk(64, 0x55);
        SessionKeys keys = crypto.split_session_key(mk);
        bool ok = (keys.sk_enc.size() == 32 && keys.sk_mac.size() == 32);
        if (ok) PASS() else FAIL("wrong sizes")
    }

    TEST("Same inputs → same derived key")
    {
        Bytes ss(32, 0x42), n1(32, 0xAA), n2(32, 0xBB), sid(32, 0xCC);
        Bytes mk1 = crypto.derive_master_session_key(ss, n1, n2, sid);
        Bytes mk2 = crypto.derive_master_session_key(ss, n1, n2, sid);
        if (mk1 == mk2) PASS() else FAIL("not deterministic")
    }

    // ---- Full protocol simulation ----
    TEST("Full KEM → derive → KC1/KC2 flow")
    {
        // OBU and RSU each have a keypair
        KeyPair obu_kp = crypto.generate_keypair();
        KeyPair rsu_kp = crypto.generate_keypair();

        // OBU encapsulates to RSU
        KEMResult kem = crypto.encapsulate(rsu_kp.public_key);
        Bytes ss_obu = kem.shared_secret;

        // RSU decapsulates
        Bytes ss_rsu = crypto.decapsulate(kem.ciphertext, rsu_kp.private_key);

        // Both should have same shared secret
        assert(ss_obu == ss_rsu);

        // Generate nonces and session ID
        Bytes nonce_obu(32, 0x11), nonce_rsu(32, 0x22);
        Bytes transcript;
        transcript.insert(transcript.end(), nonce_obu.begin(), nonce_obu.end());
        transcript.insert(transcript.end(), nonce_rsu.begin(), nonce_rsu.end());
        Bytes session_id = crypto.compute_hash(transcript);

        // Both derive the same master key
        Bytes mk_obu = crypto.derive_master_session_key(ss_obu, nonce_obu, nonce_rsu, session_id);
        Bytes mk_rsu = crypto.derive_master_session_key(ss_rsu, nonce_obu, nonce_rsu, session_id);
        assert(mk_obu == mk_rsu);

        // Split
        SessionKeys keys_obu = crypto.split_session_key(mk_obu);
        SessionKeys keys_rsu = crypto.split_session_key(mk_rsu);

        // KC1: OBU computes, RSU verifies
        Bytes kc1_input;
        std::string kc1_tag = "KC1";
        kc1_input.insert(kc1_input.end(), kc1_tag.begin(), kc1_tag.end());
        kc1_input.insert(kc1_input.end(), session_id.begin(), session_id.end());
        kc1_input.insert(kc1_input.end(), nonce_obu.begin(), nonce_obu.end());
        kc1_input.insert(kc1_input.end(), nonce_rsu.begin(), nonce_rsu.end());

        Bytes kc1_obu = crypto.compute_hmac(keys_obu.sk_mac, kc1_input);
        Bytes kc1_rsu = crypto.compute_hmac(keys_rsu.sk_mac, kc1_input);
        assert(kc1_obu == kc1_rsu);

        // KC2: RSU computes, OBU verifies (note: nonce order reversed)
        Bytes kc2_input;
        std::string kc2_tag = "KC2";
        kc2_input.insert(kc2_input.end(), kc2_tag.begin(), kc2_tag.end());
        kc2_input.insert(kc2_input.end(), session_id.begin(), session_id.end());
        kc2_input.insert(kc2_input.end(), nonce_rsu.begin(), nonce_rsu.end());
        kc2_input.insert(kc2_input.end(), nonce_obu.begin(), nonce_obu.end());

        Bytes kc2_rsu = crypto.compute_hmac(keys_rsu.sk_mac, kc2_input);
        Bytes kc2_obu = crypto.compute_hmac(keys_obu.sk_mac, kc2_input);
        assert(kc2_rsu == kc2_obu);

        PASS()
    }

    // ---- AES-256-GCM ----
    TEST("AES-GCM encrypt/decrypt roundtrip")
    {
        Bytes key(32, 0x42);
        Bytes plaintext = {0xDE, 0xAD, 0xBE, 0xEF, 0x01, 0x02, 0x03, 0x04};

        timer.start("aes_gcm_encrypt");
        Bytes encrypted = crypto.aes_gcm_encrypt(key, plaintext);
        timer.stop("aes_gcm_encrypt");

        timer.start("aes_gcm_decrypt");
        Bytes decrypted = crypto.aes_gcm_decrypt(key, encrypted);
        timer.stop("aes_gcm_decrypt");

        if (decrypted == plaintext) PASS() else FAIL("plaintext mismatch")
    }

    TEST("AES-GCM output format: 12B nonce + ct + 16B tag")
    {
        Bytes key(32, 0xAA);
        Bytes pt = {1, 2, 3, 4, 5};
        Bytes enc = crypto.aes_gcm_encrypt(key, pt);
        // Expected: 12 (nonce) + 5 (ciphertext) + 16 (tag) = 33
        if (enc.size() == 12 + pt.size() + 16) PASS()
        else FAIL("size=" + std::to_string(enc.size()) + " expected=33")
    }

    TEST("AES-GCM rejects tampered ciphertext")
    {
        Bytes key(32, 0xBB);
        Bytes pt = {10, 20, 30, 40};
        Bytes enc = crypto.aes_gcm_encrypt(key, pt);
        enc[15] ^= 0xFF; // tamper
        bool caught = false;
        try { crypto.aes_gcm_decrypt(key, enc); }
        catch (const std::runtime_error&) { caught = true; }
        if (caught) PASS() else FAIL("tampered data accepted")
    }

    TEST("AES-GCM rejects wrong key")
    {
        Bytes key1(32, 0xCC);
        Bytes key2(32, 0xDD);
        Bytes pt = {1, 2, 3};
        Bytes enc = crypto.aes_gcm_encrypt(key1, pt);
        bool caught = false;
        try { crypto.aes_gcm_decrypt(key2, enc); }
        catch (const std::runtime_error&) { caught = true; }
        if (caught) PASS() else FAIL("wrong key accepted")
    }

    TEST("AES-GCM different encryptions produce different ciphertexts")
    {
        Bytes key(32, 0xEE);
        Bytes pt = {1, 2, 3, 4, 5};
        Bytes enc1 = crypto.aes_gcm_encrypt(key, pt);
        Bytes enc2 = crypto.aes_gcm_encrypt(key, pt);
        if (enc1 != enc2) PASS() else FAIL("same ciphertext — nonce reuse!")
    }

    // ---- Timing report ----
    std::cout << "\n  Timing Results:\n";
    for (auto& [op, us] : timer.all_results()) {
        printf("    %-20s %8.1f μs  (%6.3f ms)\n", op.c_str(), us, us / 1000.0);
    }

    // ---- Summary ----
    std::cout << "\n========================================\n";
    std::cout << "  Results: " << tests_passed << " passed, "
              << tests_failed << " failed\n";
    std::cout << "========================================\n";

    return tests_failed > 0 ? 1 : 0;
}
