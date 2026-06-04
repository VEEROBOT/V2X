/**
 * File: registration_client.cpp
 * Module: V2X Authentication Testbed — RSU Registration Client
 *
 * Purpose:
 *    Handles one-time registration of RSU with Desktop server. Connects
 *    via TCP, exchanges entity ID, and receives all provisioned cryptographic
 *    keys required for authenticating OBUs.
 *
 * Author(s): Praveen Kumar
 * Company: Siliris Technologies Pvt. Ltd
 * Created: 15th February 2026
 * Version: 1.1
 *
 * Protocol Implementation:
 *    Message Format: [type: 1B][length: 4B BE][payload]
 *    \n *    Registration Steps:
 *    1. Connect to Desktop TCP port 8002 (RSU registration port)
 *    2. Send REGISTER_REQUEST with entity_id (RSU)
 *    3. Receive key material: RID, AID, DAID, SK, PK_self, OBU_pks[]
 *    4. Save keys to local key store
 *    5. Close connection
 *
 * License:
 *    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
 *    Proprietary - See LICENSE file for terms and conditions.
 */

#include "registration_client.h"

#include <sys/socket.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <cstring>
#include <stdexcept>
#include <iostream>

namespace v2x {

// Registration protocol message types (must match Desktop config.py)
static constexpr uint8_t MSG_REGISTER_REQUEST   = 0x00;
static constexpr uint8_t MSG_RID                = 0x01;
static constexpr uint8_t MSG_AID                = 0x02;
static constexpr uint8_t MSG_DAID               = 0x03;
static constexpr uint8_t MSG_PRIVATE_KEY        = 0x04;
static constexpr uint8_t MSG_PUBLIC_KEY_SELF    = 0x05;
static constexpr uint8_t MSG_PUBLIC_KEY_PEER    = 0x06;
static constexpr uint8_t MSG_REGISTER_COMPLETE  = 0x07;
static constexpr uint8_t MSG_ERROR              = 0xFF;

// ---- Socket helpers ----

static void recv_exact(int fd, uint8_t* buf, size_t n) {
    size_t received = 0;
    while (received < n) {
        ssize_t r = recv(fd, buf + received, n - received, 0);
        if (r <= 0) throw std::runtime_error("Connection closed during recv");
        received += r;
    }
}

static void send_all(int fd, const uint8_t* buf, size_t n) {
    size_t sent = 0;
    while (sent < n) {
        ssize_t s = send(fd, buf + sent, n - sent, 0);
        if (s <= 0) throw std::runtime_error("Connection closed during send");
        sent += s;
    }
}

// Pack: [type:1B] [length:4B BE] [payload]
static void send_message(int fd, uint8_t type, const Bytes& payload = {}) {
    uint8_t header[5];
    header[0] = type;
    uint32_t len = htonl(static_cast<uint32_t>(payload.size()));
    memcpy(header + 1, &len, 4);
    send_all(fd, header, 5);
    if (!payload.empty()) {
        send_all(fd, payload.data(), payload.size());
    }
}

// Recv: [type:1B] [length:4B BE] [payload]
static std::pair<uint8_t, Bytes> recv_message(int fd) {
    uint8_t header[5];
    recv_exact(fd, header, 5);
    uint8_t type = header[0];
    uint32_t net_len;
    memcpy(&net_len, header + 1, 4);
    uint32_t length = ntohl(net_len);

    Bytes payload(length);
    if (length > 0) {
        recv_exact(fd, payload.data(), length);
    }
    return {type, payload};
}

static const char* msg_name(uint8_t type) {
    switch (type) {
        case MSG_RID:               return "RID";
        case MSG_AID:               return "AID";
        case MSG_DAID:              return "DAID";
        case MSG_PRIVATE_KEY:       return "PRIVATE_KEY";
        case MSG_PUBLIC_KEY_SELF:   return "PUBLIC_KEY_SELF";
        case MSG_PUBLIC_KEY_PEER:   return "PUBLIC_KEY_PEER";
        case MSG_REGISTER_COMPLETE: return "REGISTER_COMPLETE";
        case MSG_ERROR:             return "ERROR";
        default:                    return "UNKNOWN";
    }
}

// ============================================================================
// Registration
// ============================================================================

RegistrationKeys RegistrationClient::register_with_desktop(
    const std::string& desktop_ip,
    int desktop_port,
    const std::string& entity_id)
{
    std::cout << "[REG] Connecting to Desktop " << desktop_ip
              << ":" << desktop_port << "..." << std::endl;

    // Create TCP socket
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) throw std::runtime_error("socket() failed");

    struct sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(desktop_port);
    if (inet_pton(AF_INET, desktop_ip.c_str(), &addr.sin_addr) <= 0) {
        close(fd);
        throw std::runtime_error("Invalid Desktop IP: " + desktop_ip);
    }

    if (connect(fd, reinterpret_cast<struct sockaddr*>(&addr), sizeof(addr)) < 0) {
        close(fd);
        throw std::runtime_error("connect() failed — is Desktop running?");
    }

    std::cout << "[REG] Connected. Sending REGISTER_REQUEST for '"
              << entity_id << "'..." << std::endl;

    // Send registration request
    Bytes id_bytes(entity_id.begin(), entity_id.end());
    send_message(fd, MSG_REGISTER_REQUEST, id_bytes);

    // Receive all keys
    RegistrationKeys keys;
    bool done = false;

    while (!done) {
        auto [type, payload] = recv_message(fd);
        std::cout << "[REG] ← " << msg_name(type) << ": "
                  << payload.size() << " bytes" << std::endl;

        switch (type) {
            case MSG_RID:
                keys.rid = payload;
                break;
            case MSG_AID:
                keys.aid = payload;
                break;
            case MSG_DAID:
                keys.daid = payload;
                break;
            case MSG_PRIVATE_KEY:
                keys.sk = payload;
                break;
            case MSG_PUBLIC_KEY_SELF:
                keys.pk_self = payload;
                break;
            case MSG_PUBLIC_KEY_PEER: {
                // Parse: [count:1B] [id_len:1B id_bytes pk_bytes] ...
                if (payload.size() >= 1) {
                    uint8_t count = payload[0];
                    size_t offset = 1;
                    for (uint8_t i = 0; i < count && offset < payload.size(); ++i) {
                        uint8_t id_len = payload[offset++];
                        std::string peer_id(payload.begin() + offset,
                                           payload.begin() + offset + id_len);
                        offset += id_len;

                        // Remaining bytes for this peer = until next peer or end
                        // PK size: we need to figure this out from the total.
                        // For now, compute: remaining per peer =
                        //   (payload.size() - offset) / (count - i) approximately
                        // Better: since all PKs are same size from one provider,
                        // figure out pk_size from first key we received
                        size_t pk_size = keys.pk_self.size();
                        if (pk_size == 0) pk_size = 65; // fallback placeholder

                        Bytes peer_pk(payload.begin() + offset,
                                     payload.begin() + offset + pk_size);
                        offset += pk_size;

                        keys.peer_pks.push_back({peer_id, peer_pk});
                        std::cout << "[REG]   Peer: " << peer_id
                                  << " (PK: " << peer_pk.size() << " bytes)"
                                  << std::endl;
                    }
                }
                break;
            }
            case MSG_REGISTER_COMPLETE:
                done = true;
                break;
            case MSG_ERROR:
                close(fd);
                throw std::runtime_error("Registration error: " +
                    std::string(payload.begin(), payload.end()));
            default:
                std::cout << "[REG] WARNING: Unknown message type 0x"
                          << std::hex << (int)type << std::dec << std::endl;
        }
    }

    close(fd);

    std::cout << "[REG] ✓ Registration complete. Keys received:" << std::endl;
    std::cout << "  RID:  " << keys.rid.size() << " bytes" << std::endl;
    std::cout << "  AID:  " << keys.aid.size() << " bytes" << std::endl;
    std::cout << "  DAID: " << keys.daid.size() << " bytes" << std::endl;
    std::cout << "  SK:   " << keys.sk.size() << " bytes" << std::endl;
    std::cout << "  PK:   " << keys.pk_self.size() << " bytes" << std::endl;
    std::cout << "  Peers: " << keys.peer_pks.size() << std::endl;

    return keys;
}

} // namespace v2x
