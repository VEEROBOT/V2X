#pragma once
#include <string>
#include <vector>
#include <cstdint>
#include <optional>

namespace v2x {

class UdpClient {
public:
    UdpClient(const std::string& bind_ip, int listen_port,
              const std::string& rsu_ip, int rsu_port);
    ~UdpClient();

    void open();
    void close_socket();

    /** Send packet to RSU. */
    bool send_to_rsu(const std::vector<uint8_t>& data);

    /**
     * Receive a packet (blocking with timeout).
     * Returns nullopt on timeout.
     */
    std::optional<std::vector<uint8_t>> receive(int timeout_ms);

private:
    std::string bind_ip_;
    int listen_port_;
    std::string rsu_ip_;
    int rsu_port_;
    int fd_;
};

} // namespace v2x
