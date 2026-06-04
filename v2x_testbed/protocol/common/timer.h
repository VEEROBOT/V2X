#pragma once
#include <chrono>
#include <string>
#include <unordered_map>

namespace v2x {

class Timer {
public:
    void start(const std::string& operation) {
        starts_[operation] = std::chrono::high_resolution_clock::now();
    }

    double stop(const std::string& operation) {
        auto end = std::chrono::high_resolution_clock::now();
        auto it = starts_.find(operation);
        if (it == starts_.end()) return -1.0;
        double us = std::chrono::duration<double, std::micro>(end - it->second).count();
        results_[operation] = us;
        starts_.erase(it);
        return us;
    }

    double get_us(const std::string& operation) const {
        auto it = results_.find(operation);
        return (it != results_.end()) ? it->second : -1.0;
    }

    double get_ms(const std::string& operation) const {
        double us = get_us(operation);
        return (us >= 0) ? us / 1000.0 : -1.0;
    }

    const std::unordered_map<std::string, double>& all_results() const {
        return results_;
    }

    void clear() { starts_.clear(); results_.clear(); }

private:
    std::unordered_map<std::string, std::chrono::high_resolution_clock::time_point> starts_;
    std::unordered_map<std::string, double> results_;  // microseconds
};

} // namespace v2x
