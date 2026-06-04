#pragma once
#include "udp_client.h"
#include "registration_client.h"

#include "crypto/crypto_provider.h"
#include "packets/packet_serializer.h"
#include "common/timer.h"

#include <string>

enum class TestMode {
    NONE,
    CORRUPT_SIGNATURE,
    OLD_TIMESTAMP,
    REPLAY
};

namespace v2x {

struct AuthResult {
    bool success;
    std::string session_id_hex;
    double total_latency_ms;
    std::string failure_reason;
    Timer timing;
    Bytes sk_enc;    // Session encryption key (for post-auth messaging)
    Bytes sk_mac;    // Session MAC key
    Bytes session_id;
};

class AuthClient {
public:
AuthClient(CryptoProvider* crypto,
           UdpClient& udp,
           const RegistrationKeys& keys,
           const std::string& entity_id,
           bool is_emergency,
           int delta_ts_ms,
           TestMode test_mode);

    /**
     * Run a single full authentication cycle (Steps 1-32).
     * Blocking — returns when session is established or fails.
     */
    AuthResult authenticate();

    /**
     * Send an encrypted post-auth message using established session keys.
     * Payload is encrypted with AES-GCM(sk_enc) and MACed with HMAC(sk_mac).
     */
    bool send_post_auth_message(const Bytes& plaintext,
                                const Bytes& sk_enc,
                                const Bytes& sk_mac);

private:
    CryptoProvider* crypto_;
    PacketSerializer serializer_;
    UdpClient& udp_;
    RegistrationKeys keys_;
    std::string entity_id_;
    bool is_emergency_;
    int delta_ts_us_;
    Bytes master_secret_;
    TestMode test_mode_;
    std::vector<uint8_t> last_auth_request_;    
};

} // namespace v2x
