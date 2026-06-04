#pragma once
#include "crypto/crypto_provider.h"
#include <string>
#include <unordered_map>
#include <mutex>
#include <chrono>

namespace v2x {

enum class SessionState {
    CREATED,
    AWAITING_KC1,
    ACTIVE,
    EXPIRED,
    ABORTED
};

struct SessionEntry {
    Bytes session_id;       // 32 bytes
    Bytes pid_obu;          // 32 bytes
    Bytes pid_rsu;          // 32 bytes
    std::string obu_ip;
    int obu_port;
    Bytes sk_enc;           // 32 bytes
    Bytes sk_mac;           // 32 bytes
    Bytes nonce_obu;        // 32 bytes (kept for KC verification)
    Bytes nonce_rsu;        // 32 bytes
    SessionState state;
    std::chrono::steady_clock::time_point created_at;
    std::chrono::steady_clock::time_point last_activity;
    bool is_emergency;
};

class SessionManager {
public:
    explicit SessionManager(int timeout_seconds)
        : timeout_sec_(timeout_seconds) {}

    /**
     * Create a new session. Key: PID_OBU hex.
     */
    void create_session(const SessionEntry& entry) {
        std::lock_guard<std::mutex> lock(mtx_);
        std::string key = pid_to_key(entry.pid_obu);
        sessions_[key] = entry;
        sessions_[key].state = SessionState::AWAITING_KC1;
        sessions_[key].created_at = std::chrono::steady_clock::now();
        sessions_[key].last_activity = sessions_[key].created_at;
    }

    /**
     * Look up session by PID_OBU.
     */
    SessionEntry* find_by_pid(const Bytes& pid_obu) {
        std::lock_guard<std::mutex> lock(mtx_);
        auto it = sessions_.find(pid_to_key(pid_obu));
        return (it != sessions_.end()) ? &it->second : nullptr;
    }

    /**
     * Look up session by OBU IP + port (for KC1 packets which don't contain PID).
     * Returns the most recent AWAITING_KC1 session for that address.
     */
    SessionEntry* find_by_address(const std::string& ip, int port) {
        std::lock_guard<std::mutex> lock(mtx_);
        for (auto& [key, entry] : sessions_) {
            if (entry.obu_ip == ip && entry.obu_port == port &&
                entry.state == SessionState::AWAITING_KC1) {
                return &entry;
            }
        }
        return nullptr;
    }

    /**
     * Find active session by address (for post-auth messages).
     */
    SessionEntry* find_active_by_address(const std::string& ip, int port) {
        std::lock_guard<std::mutex> lock(mtx_);
        for (auto& [key, entry] : sessions_) {
            if (entry.obu_ip == ip && entry.obu_port == port &&
                entry.state == SessionState::ACTIVE) {
                return &entry;
            }
        }
        return nullptr;
    }

    void set_state(const Bytes& pid_obu, SessionState state) {
        std::lock_guard<std::mutex> lock(mtx_);
        auto it = sessions_.find(pid_to_key(pid_obu));
        if (it != sessions_.end()) {
            it->second.state = state;
            it->second.last_activity = std::chrono::steady_clock::now();
        }
    }

    void set_emergency(const Bytes& pid_obu, bool is_emergency) {
        std::lock_guard<std::mutex> lock(mtx_);
        auto it = sessions_.find(pid_to_key(pid_obu));
        if (it != sessions_.end()) {
            it->second.is_emergency = is_emergency;
        }
    }

    /**
     * Remove expired sessions. Returns count removed.
     */
    int cleanup_expired() {
        std::lock_guard<std::mutex> lock(mtx_);
        auto now = std::chrono::steady_clock::now();
        int removed = 0;

        for (auto it = sessions_.begin(); it != sessions_.end(); ) {
            auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(
                now - it->second.last_activity).count();
            if (elapsed > timeout_sec_) {
                it = sessions_.erase(it);
                removed++;
            } else {
                ++it;
            }
        }
        return removed;
    }

    size_t active_count() const {
        std::lock_guard<std::mutex> lock(mtx_);
        size_t count = 0;
        for (auto& [k, e] : sessions_) {
            if (e.state == SessionState::ACTIVE) count++;
        }
        return count;
    }

    /** Returns true if at least one ACTIVE session is flagged as emergency. */
    bool has_active_emergency() const {
        std::lock_guard<std::mutex> lock(mtx_);
        for (auto& [k, e] : sessions_) {
            if (e.state == SessionState::ACTIVE && e.is_emergency) return true;
        }
        return false;
    }

private:
    std::unordered_map<std::string, SessionEntry> sessions_;
    mutable std::mutex mtx_;
    int timeout_sec_;

    static std::string pid_to_key(const Bytes& pid) {
        std::string key;
        for (auto b : pid) {
            char buf[3];
            snprintf(buf, sizeof(buf), "%02x", b);
            key += buf;
        }
        return key;
    }
};

} // namespace v2x
