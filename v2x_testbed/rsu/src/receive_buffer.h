#pragma once
#include <vector>
#include <cstdint>
#include <string>
#include <mutex>
#include <atomic>
#include <optional>

namespace v2x {

class ReceiveBuffer {
public:
    struct Packet {
        std::vector<uint8_t> data;
        std::string sender_ip;
        int sender_port = 0;
    };

    explicit ReceiveBuffer(size_t capacity)
        : capacity_(capacity), head_(0), count_(0),
          total_received_(0), total_dropped_(0) {
        slots_.resize(capacity);
    }

    bool push(std::vector<uint8_t> data, const std::string& ip, int port) {
        std::lock_guard<std::mutex> lock(mtx_);
        total_received_++;

        if (count_ >= capacity_) {
            total_dropped_++;
            return false;
        }

        size_t write_idx = (head_ + count_) % capacity_;
        slots_[write_idx].data = std::move(data);
        slots_[write_idx].sender_ip = ip;
        slots_[write_idx].sender_port = port;
        count_++;
        return true;
    }

    std::optional<Packet> pop() {
        std::lock_guard<std::mutex> lock(mtx_);
        if (count_ == 0) return std::nullopt;

        Packet pkt = std::move(slots_[head_]);
        head_ = (head_ + 1) % capacity_;
        count_--;
        return pkt;
    }

    size_t get_count() const { std::lock_guard<std::mutex> lock(mtx_); return count_; }
    uint64_t get_total_received() const { return total_received_.load(); }
    uint64_t get_total_dropped() const { return total_dropped_.load(); }
    double get_loss_ratio() const {
        uint64_t total = total_received_.load();
        return (total > 0) ? static_cast<double>(total_dropped_.load()) / total : 0.0;
    }
    size_t get_capacity() const { return capacity_; }

    void reset_stats() {
        total_received_ = 0;
        total_dropped_ = 0;
    }

private:
    size_t capacity_;
    size_t head_;
    size_t count_;
    std::vector<Packet> slots_;
    mutable std::mutex mtx_;
    std::atomic<uint64_t> total_received_;
    std::atomic<uint64_t> total_dropped_;
};

} // namespace v2x
