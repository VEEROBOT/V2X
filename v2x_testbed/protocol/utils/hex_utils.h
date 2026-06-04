#pragma once
#include <string>
#include <vector>
#include <cstdint>
#include <sstream>
#include <iomanip>

namespace v2x {

inline std::string to_hex(const std::vector<uint8_t>& data, size_t max_len = 0) {
    std::ostringstream ss;
    size_t n = (max_len > 0 && max_len < data.size()) ? max_len : data.size();
    for (size_t i = 0; i < n; ++i)
        ss << std::hex << std::setfill('0') << std::setw(2) << (int)data[i];
    if (max_len > 0 && max_len < data.size()) ss << "...";
    return ss.str();
}

inline std::vector<uint8_t> from_hex(const std::string& hex) {
    std::vector<uint8_t> data;
    for (size_t i = 0; i + 1 < hex.size(); i += 2) {
        data.push_back(static_cast<uint8_t>(std::stoi(hex.substr(i, 2), nullptr, 16)));
    }
    return data;
}

} // namespace v2x
