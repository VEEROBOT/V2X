#pragma once
#include "crypto/crypto_provider.h"
#include <string>

namespace v2x {

/**
 * Keys received from Desktop during registration.
 */
struct RegistrationKeys {
    Bytes rid;
    Bytes aid;
    Bytes daid;
    Bytes sk;           // Own private key
    Bytes pk_self;      // Own public key
    // Peer PKs: for RSU these are OBU public keys
    struct PeerKey {
        std::string peer_id;
        Bytes pk;
    };
    std::vector<PeerKey> peer_pks;
};

class RegistrationClient {
public:
    /**
     * Connect to Desktop and register.
     * Returns all keys on success, throws on failure.
     */
    static RegistrationKeys register_with_desktop(
        const std::string& desktop_ip,
        int desktop_port,
        const std::string& entity_id
    );
};

} // namespace v2x
