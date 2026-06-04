#pragma once
#include "receive_buffer.h"
#include "session_manager.h"
#include "udp_server.h"
#include "log_sender.h"
#include "registration_client.h"

#include "crypto/crypto_provider.h"
#include "packets/packet_serializer.h"
#include "common/timer.h"
#include <unordered_set>

#include <thread>
#include <atomic>

namespace v2x {

/**
 * RSU Packet Processor (LLD Section 9.2)
 * Reads packets from receive buffer, runs the auth state machine,
 * sends responses via UDP, and logs events to Desktop.
 */
class PacketProcessor {
public:
    PacketProcessor(CryptoProvider* crypto,
                    ReceiveBuffer& buffer,
                    UdpServer& udp,
                    SessionManager& sessions,
                    LogSender& logger,
                    const RegistrationKeys& keys,
                    int delta_ts_ms,
                    const std::string& car_alert_ip = "",
                    int car_alert_port = 5001);

    void start();
    void stop();

    /**
     * Send a UDP alert to the car's v2x_bridge_node.
     * active=true  → EMERGENCY_ACTIVE   (ambulance authenticated)
     * active=false → EMERGENCY_CLEARED  (emergency session expired)
     */
    void send_car_alert(bool active, const std::string& session_id_hex = "");

private:
    CryptoProvider* crypto_;
    PacketSerializer serializer_;
    ReceiveBuffer& buffer_;
    UdpServer& udp_;
    SessionManager& sessions_;
    LogSender& logger_;

    RegistrationKeys keys_;
    Bytes master_secret_;   // For PID generation
    int delta_ts_us_;       // Threshold in microseconds

    std::string car_alert_ip_;
    int car_alert_port_;

    std::atomic<bool> running_;
    std::thread thread_;
    std::unordered_set<std::string> seen_pids_;

    void process_loop();
    void handle_packet(const ReceiveBuffer::Packet& pkt);

    void handle_auth_request(const Bytes& data,
                             const std::string& sender_ip, int sender_port);
    void handle_kc1(const Bytes& data,
                    const std::string& sender_ip, int sender_port);
    void handle_post_auth(const Bytes& data,
                          const std::string& sender_ip, int sender_port);

    /** Build and send a JSON log event. */
    void log_event(const std::string& event_type,
                   const std::string& source,
                   const std::string& target,
                   const std::string& session_id_hex,
                   const std::string& details_json,
                   const Timer& timer);
};

} // namespace v2x
