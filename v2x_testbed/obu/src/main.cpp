/**
 * File: main.cpp
 * Module: V2X Authentication Testbed — OBU Client
 *
 * Purpose:
 *    Entry point for the On-Board Unit (vehicle) client. Orchestrates
 *    registration with Desktop, connectivity to RSU, and executes the
 *    complete 32-step V2X authentication protocol.
 *
 * Author(s): Praveen Kumar
 * Company: Siliris Technologies Pvt. Ltd
 * Created: 15th February 2026
 * Version: 1.1
 *
 * Key Functions:
 *    - Load configuration (entity ID, crypto provider, connection parameters)
 *    - Register with Desktop to obtain cryptographic keys
 *    - Establish UDP connection to RSU
 *    - Execute authentication protocol (32-step flow)
 *    - Derive session keys and confirm mutual authentication
 *    - Support multiple authentication cycles (--loop N)
 *
 * Usage: ./obu_client [config_path] [--loop N]
 *   Default config: ./config/obu1_config.json
 *   --loop N: run N authentication cycles (default: 1)
 *
 * License:
 *    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
 *    Proprietary - See LICENSE file for terms and conditions.
 */

#include "registration_client.h"
#include "udp_client.h"
#include "auth_client.h"

#include "crypto/placeholder_provider.h"
#include "crypto/lattice_provider.h"
#include "common/config_reader.h"
#include "common/key_store.h"
#include "utils/hex_utils.h"

#include <iostream>
#include <memory>
#include <filesystem>
#include <thread>
#include <chrono>
#include <cstring>

using namespace v2x;

int main(int argc, char* argv[]) {
    std::cout << "============================================================" << std::endl;
    std::cout << "  V2X Authentication Testbed — OBU Client" << std::endl;
    std::cout << "============================================================" << std::endl;

    // ---- Parse args ----
    std::string config_path = "config/obu1_config.json";
    int loop_count = 1;
    bool force_register = false;

    TestMode test_mode = TestMode::NONE;

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];

        if (arg == "--loop" && i + 1 < argc) {
            loop_count = std::atoi(argv[++i]);
        }
        else if (arg == "--force-register") {
            force_register = true;
        }
        else if (arg == "--test-mode=corrupt_signature") {
            test_mode = TestMode::CORRUPT_SIGNATURE;
        }
        else if (arg == "--test-mode=old_timestamp") {
            test_mode = TestMode::OLD_TIMESTAMP;
        }
        else if (arg == "--test-mode=replay") {
            test_mode = TestMode::REPLAY;
        }
        else if (arg[0] != '-') {
            config_path = arg;
        }
    }    

    // ---- Load config ----
    std::cout << "[OBU] Loading config: " << config_path << std::endl;

    ConfigReader config(config_path);
    std::string entity_id    = config.get_string("entity_id", "OBU1");
    std::string obu_ip       = config.get_string("obu_ip", "0.0.0.0");
    int listen_port          = config.get_int("udp_listen_port", 5001);
    std::string rsu_ip       = config.get_string("rsu_ip", "127.0.0.1");
    int rsu_port             = config.get_int("rsu_port", 5000);
    std::string desktop_ip   = config.get_string("desktop_ip", "127.0.0.1");
    int desktop_reg_port     = config.get_int("desktop_reg_port", 8001);
    bool is_emergency        = config.get_bool("is_emergency", false);
    int delta_ts_ms          = config.get_int("delta_ts_ms", 50);
    std::string provider     = config.get_string("crypto_provider", "placeholder");
    std::string key_dir      = config.get_string("key_directory", "./keys/");

    std::cout << "[OBU] Entity: " << entity_id
              << (is_emergency ? " [EMERGENCY]" : "") << std::endl;
    std::cout << "[OBU] RSU:    " << rsu_ip << ":" << rsu_port << std::endl;
    std::cout << "[OBU] Crypto: " << provider << std::endl;

    // ---- Create crypto provider ----
    std::unique_ptr<CryptoProvider> crypto;
    if (provider == "lattice") {
        crypto = std::make_unique<LatticeProvider>();
    } else {
        crypto = std::make_unique<PlaceholderProvider>();
    }

    // ---- Register or load keys ----
    RegistrationKeys keys;
    KeyStore store(key_dir);
    std::filesystem::create_directories(key_dir);

    std::string sk_name = entity_id + "_sk";
    // Use lowercase for file names
    for (auto& c : sk_name) c = std::tolower(c);

    bool need_register = force_register || !store.exists(sk_name);

    if (!need_register) {
        std::cout << "[OBU] Loading saved keys from " << key_dir << std::endl;
        std::string prefix = entity_id;
        for (auto& c : prefix) c = std::tolower(c);

        keys.rid     = store.load(prefix + "_rid");
        keys.aid     = store.load(prefix + "_aid");
        keys.daid    = store.load(prefix + "_daid");
        keys.sk      = store.load(prefix + "_sk");
        keys.pk_self = store.load(prefix + "_pk");

        // Load peer keys
        for (auto& entry : std::filesystem::directory_iterator(key_dir)) {
            std::string fname = entry.path().stem().string();
            if (fname.find("_pk") != std::string::npos &&
                fname.find(prefix) == std::string::npos) {
                std::string peer_id = fname.substr(0, fname.find("_pk"));
                keys.peer_pks.push_back({peer_id, store.load(fname)});
                std::cout << "[OBU]   Loaded peer: " << peer_id << std::endl;
            }
        }

        // If no peer keys found, force re-registration
        if (keys.peer_pks.empty()) {
            std::cout << "[OBU] WARNING: No peer keys found. Re-registering..." << std::endl;
            need_register = true;
        }
    }

    if (need_register) {
        std::cout << std::endl;
        keys = RegistrationClient::register_with_desktop(
            desktop_ip, desktop_reg_port, entity_id);

        if (keys.peer_pks.empty()) {
            std::cerr << "[OBU] ERROR: No peer public keys received from Desktop!" << std::endl;
            std::cerr << "[OBU] Make sure RSU is registered BEFORE OBU." << std::endl;
            std::cerr << "[OBU] Startup order: Desktop → RSU → OBU" << std::endl;
            return 1;
        }

        // Save keys
        std::string prefix = entity_id;
        for (auto& c : prefix) c = std::tolower(c);

        store.save(prefix + "_rid", keys.rid);
        store.save(prefix + "_aid", keys.aid);
        store.save(prefix + "_daid", keys.daid);
        store.save(prefix + "_sk", keys.sk);
        store.save(prefix + "_pk", keys.pk_self);
        for (auto& peer : keys.peer_pks) {
            store.save(peer.peer_id + "_pk", peer.pk);
        }
        std::cout << "[OBU] Keys saved to " << key_dir << std::endl;
    }

    // ---- Open UDP ----
    UdpClient udp(obu_ip, listen_port, rsu_ip, rsu_port);
    udp.open();

    // ---- Create auth client ----
    // AuthClient auth(crypto.get(), udp, keys, entity_id, is_emergency, delta_ts_ms);

    AuthClient auth(
    crypto.get(),
    udp,
    keys,
    entity_id,
    is_emergency,
    delta_ts_ms,
    test_mode
    );

    // ---- Run authentication ----
    std::cout << std::endl;
    std::cout << "============================================================" << std::endl;
    std::cout << "  Running " << loop_count << " authentication cycle(s)..." << std::endl;
    std::cout << "============================================================" << std::endl;

    int success_count = 0;
    int fail_count = 0;
    double total_latency_ms = 0;
    auto start_time = std::chrono::steady_clock::now();

    for (int i = 0; i < loop_count; ++i) {
        if (loop_count > 1) {
            std::cout << "\n--- Cycle " << (i + 1) << " / "
                      << loop_count << " ---" << std::endl;
        }

        AuthResult result = auth.authenticate();

        if (result.success) {
            success_count++;
            total_latency_ms += result.total_latency_ms;

            // Send post-auth encrypted message
            // Build payload: JSON with entity info and emergency flag
            std::string payload_str = "{\"entity_id\":\"" + entity_id +
                "\",\"is_emergency\":" + (is_emergency ? "true" : "false") +
                ",\"session_id\":\"" + result.session_id_hex +
                "\",\"message\":\"V2X_STATUS_OK\"}";
            Bytes payload(payload_str.begin(), payload_str.end());

            auth.send_post_auth_message(payload, result.sk_enc, result.sk_mac);

            if (is_emergency) {
                std::cout << "[OBU] 🚑 Emergency priority flag sent" << std::endl;
            }
        } else {
            fail_count++;
            std::cout << "[OBU] FAILED: " << result.failure_reason << std::endl;
        }

        // Brief pause between cycles
        if (loop_count > 1 && i < loop_count - 1) {
            std::this_thread::sleep_for(std::chrono::milliseconds(500));
        }
    }

    // ---- Summary ----
    if (loop_count > 1) {
        std::cout << "\n============================================================" << std::endl;
        std::cout << "  Results: " << success_count << " success, "
                  << fail_count << " failed" << std::endl;
        if (success_count > 0) {
            std::cout << "  Avg latency: "
                      << (total_latency_ms / success_count) << " ms" << std::endl;
        }
        std::cout << "============================================================" << std::endl;
    }

    // ---- Throughput summary (for automated collection) ----
    if (loop_count >= 5) {
        auto end_time = std::chrono::steady_clock::now();
        double wall_sec = std::chrono::duration_cast<std::chrono::microseconds>(
            end_time - start_time).count() / 1e6;
        double throughput = (wall_sec > 0) ? success_count / wall_sec : 0;

        std::cout << "\n[PERF] ──────────────────────────────────" << std::endl;
        std::cout << "[PERF] Throughput Test Results:" << std::endl;
        std::cout << "[PERF]   Duration:    " << wall_sec << " seconds" << std::endl;
        std::cout << "[PERF]   Attempts:    " << loop_count << std::endl;
        std::cout << "[PERF]   Successful:  " << success_count << std::endl;
        std::cout << "[PERF]   Throughput:  " << throughput << " auth/sec" << std::endl;
        std::cout << "[PERF]   Avg latency: "
                  << (success_count > 0 ? total_latency_ms / success_count : 0) << " ms" << std::endl;
        std::cout << "[PERF] ──────────────────────────────────" << std::endl;
    }

    udp.close_socket();
    return (fail_count > 0) ? 1 : 0;
}
