/**
 * File: main.cpp
 * Module: V2X Authentication Testbed — RSU Server
 *
 * Purpose:
 *    Entry point for the Roadside Unit (RSU) server. Manages vehicle
 *    authentication, session tracking, and audit logging for V2X communications.
 *
 * Author(s): Praveen Kumar
 * Company: Siliris Technologies Pvt. Ltd
 * Created: 15th February 2026
 * Version: 1.1
 *
 * Key Functions:
 *    1. Load config from JSON
 *    2. Register with Desktop (one-time TCP connection on port 8002)
 *    3. Save provisioned keys locally
 *    4. Start log sender (TCP to Desktop:9000 for audit logs)
 *    5. Start UDP listener on configured port (default: 5000)
 *    6. Process authentication packets with state machine
 *    7. Manage active sessions with cleanup timers
 *
 * Usage: ./rsu_server [config_path]
 *   Default config: ./config/rsu_config.json
 *
 * License:
 *    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
 *    Proprietary - See LICENSE file for terms and conditions.
 */

#include "registration_client.h"
#include "receive_buffer.h"
#include "session_manager.h"
#include "udp_server.h"
#include "packet_processor.h"
#include "log_sender.h"

#include "crypto/placeholder_provider.h"
#include "crypto/lattice_provider.h"
#include "common/config_reader.h"

#include <sstream>
#include "common/key_store.h"
#include "utils/hex_utils.h"

#include <iostream>
#include <memory>
#include <csignal>
#include <thread>
#include <atomic>
#include <filesystem>

using namespace v2x;

static std::atomic<bool> g_running{true};

static void signal_handler(int) {
    g_running = false;
}

int main(int argc, char* argv[]) {
    std::cout << "============================================================" << std::endl;
    std::cout << "  V2X Authentication Testbed — RSU Server" << std::endl;
    std::cout << "============================================================" << std::endl;

    // ---- Signal handling ----
    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);

    // ---- Load config ----
    std::string config_path = (argc > 1) ? argv[1] : "config/rsu_config.json";
    std::cout << "[RSU] Loading config: " << config_path << std::endl;

    ConfigReader config(config_path);
    std::string entity_id    = config.get_string("entity_id", "RSU");
    std::string rsu_ip       = config.get_string("rsu_ip", "0.0.0.0");
    int udp_port             = config.get_int("udp_port", 5000);
    std::string desktop_ip   = config.get_string("desktop_ip", "127.0.0.1");
    int desktop_log_port     = config.get_int("desktop_log_port", 9000);
    int desktop_reg_port     = config.get_int("desktop_reg_port", 8002);
    int delta_ts_ms          = config.get_int("delta_ts_ms", 50);
    int buffer_size          = config.get_int("receive_buffer_size", 50);
    int session_timeout      = config.get_int("session_timeout_seconds", 300);
    std::string provider     = config.get_string("crypto_provider", "placeholder");
    std::string key_dir      = config.get_string("key_directory", "./keys/");
    std::string car_alert_ip = config.get_string("car_alert_ip", "");
    int car_alert_port       = config.get_int("car_alert_port", 5001);

    std::cout << "[RSU] Entity: " << entity_id << std::endl;
    std::cout << "[RSU] Crypto: " << provider << std::endl;
    std::cout << "[RSU] ΔTS:    " << delta_ts_ms << " ms" << std::endl;
    std::cout << "[RSU] Buffer: " << buffer_size << " packets" << std::endl;

    // ---- Create crypto provider ----
    std::unique_ptr<CryptoProvider> crypto;
    if (provider == "lattice") {
        crypto = std::make_unique<LatticeProvider>();
    } else {
        crypto = std::make_unique<PlaceholderProvider>();
    }

    // ---- Register with Desktop OR load saved keys ----
    RegistrationKeys keys;
    KeyStore store(key_dir);
    std::filesystem::create_directories(key_dir);

    if (store.exists("rsu_sk")) {
        // Keys already saved — load them
        std::cout << "[RSU] Loading saved keys from " << key_dir << std::endl;
        keys.rid     = store.load("rsu_rid");
        keys.aid     = store.load("rsu_aid");
        keys.daid    = store.load("rsu_daid");
        keys.sk      = store.load("rsu_sk");
        keys.pk_self = store.load("rsu_pk");

        // Load peer keys (scan for obu*_pk files)
        for (auto& entry : std::filesystem::directory_iterator(key_dir)) {
            std::string fname = entry.path().stem().string();
            if (fname.find("_pk") != std::string::npos && fname.find("rsu") == std::string::npos) {
                std::string peer_id = fname.substr(0, fname.find("_pk"));
                keys.peer_pks.push_back({peer_id, store.load(fname)});
                std::cout << "[RSU]   Loaded peer: " << peer_id << std::endl;
            }
        }
    } else {
        // First run — register with Desktop
        std::cout << std::endl;
        keys = RegistrationClient::register_with_desktop(
            desktop_ip, desktop_reg_port, entity_id);

        // Save keys for next time
        store.save("rsu_rid", keys.rid);
        store.save("rsu_aid", keys.aid);
        store.save("rsu_daid", keys.daid);
        store.save("rsu_sk", keys.sk);
        store.save("rsu_pk", keys.pk_self);
        for (auto& peer : keys.peer_pks) {
            store.save(peer.peer_id + "_pk", peer.pk);
        }
        std::cout << "[RSU] Keys saved to " << key_dir << std::endl;
    }

    std::cout << std::endl;

    // ---- Start log sender ----
    LogSender logger(desktop_ip, desktop_log_port);
    logger.start();

    // ---- Start receive buffer + UDP server ----
    ReceiveBuffer recv_buffer(buffer_size);
    UdpServer udp(rsu_ip, udp_port, recv_buffer);
    udp.start();

    // ---- Start session manager ----
    SessionManager sessions(session_timeout);

    // ---- Start packet processor ----
    PacketProcessor processor(crypto.get(), recv_buffer, udp, sessions,
                              logger, keys, delta_ts_ms,
                              car_alert_ip, car_alert_port);
    processor.start();

    if (!car_alert_ip.empty()) {
        std::cout << "[RSU] Car alert target: " << car_alert_ip
                  << ":" << car_alert_port << std::endl;
    } else {
        std::cout << "[RSU] Car alert: disabled (set car_alert_ip in config)" << std::endl;
    }

    // ---- Print status ----
    std::cout << std::endl;
    std::cout << "  UDP server:      " << rsu_ip << ":" << udp_port << std::endl;
    std::cout << "  Log sender:      " << desktop_ip << ":" << desktop_log_port << std::endl;
    std::cout << "  Buffer size:     " << buffer_size << " packets" << std::endl;
    std::cout << std::endl;
    std::cout << "============================================================" << std::endl;
    std::cout << "  RSU ready. Waiting for AuthRequests..." << std::endl;
    std::cout << "  Press Ctrl+C to stop." << std::endl;
    std::cout << "============================================================" << std::endl;
    std::cout << std::endl;

    // ---- Main loop: periodic session cleanup ----
    bool emergency_was_active = false;

    while (g_running) {
        std::this_thread::sleep_for(std::chrono::seconds(10));

        // Check emergency state BEFORE cleanup so we can detect transitions
        bool emergency_now = sessions.has_active_emergency();

        int removed = sessions.cleanup_expired();
        if (removed > 0) {
            std::cout << "[RSU] Cleaned up " << removed << " expired sessions" << std::endl;
        }

        // After cleanup: if emergency was active but is now gone → notify car to clear
        bool emergency_after = sessions.has_active_emergency();
        if (emergency_was_active && !emergency_after) {
            std::cout << "[RSU] Emergency session expired — notifying car" << std::endl;
            processor.send_car_alert(false);
        }
        emergency_was_active = emergency_after;

        // Print stats periodically
        std::cout << "[RSU] Buffer: " << recv_buffer.get_count() << "/"
                  << recv_buffer.get_capacity()
                  << " | Received: " << recv_buffer.get_total_received()
                  << " | Dropped: " << recv_buffer.get_total_dropped()
                  << " | Active sessions: " << sessions.active_count()
                  << (emergency_after ? " [EMERGENCY ACTIVE]" : "")
                  << std::endl;
    }

    // ---- Shutdown ----
    std::cout << "\n[RSU] Shutting down..." << std::endl;

    // Report final buffer stats for packet loss measurement
    uint64_t total_recv = recv_buffer.get_total_received();
    uint64_t total_drop = recv_buffer.get_total_dropped();
    double loss_ratio = recv_buffer.get_loss_ratio();

    std::cout << "[RSU] Final buffer stats:" << std::endl;
    std::cout << "[RSU]   Received: " << total_recv << std::endl;
    std::cout << "[RSU]   Dropped:  " << total_drop << std::endl;
    std::cout << "[RSU]   Loss:     " << (loss_ratio * 100) << "%" << std::endl;

    // Send buffer stats to Desktop for DB recording
    std::ostringstream json;
    json << "{"
         << "\"timestamp\":\"" << "shutdown" << "\","
         << "\"event_type\":\"BUFFER_STATS\","
         << "\"source\":\"RSU\","
         << "\"target\":\"\","
         << "\"session_id\":\"\","
         << "\"details\":{"
         << "\"buffer_size\":" << buffer_size << ","
         << "\"total_received\":" << total_recv << ","
         << "\"total_dropped\":" << total_drop << ","
         << "\"loss_ratio\":" << loss_ratio
         << "},"
         << "\"crypto_timing\":{},"
         << "\"crypto_provider\":\"" << crypto->get_provider_name() << "\""
         << "}";
    logger.send_event(json.str());

    // Allow log to flush
    std::this_thread::sleep_for(std::chrono::milliseconds(200));

    processor.stop();
    udp.stop();
    logger.stop();
    std::cout << "[RSU] Goodbye." << std::endl;

    return 0;
}
