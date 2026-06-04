#pragma once
#include "receive_buffer.h"
#include <string>
#include <thread>
#include <atomic>
#include <functional>

namespace v2x {

class UdpServer {
public:
    UdpServer(const std::string& bind_ip, int port, ReceiveBuffer& buffer);
    ~UdpServer();

    void start();
    void stop();

    /** Send a UDP packet to a specific address. */
    bool send_to(const std::vector<uint8_t>& data,
                 const std::string& ip, int port);

    int get_fd() const { return fd_; }

private:
    std::string bind_ip_;
    int port_;
    int fd_;
    ReceiveBuffer& buffer_;
    std::atomic<bool> running_;
    std::thread thread_;

    void listen_loop();
};

} // namespace v2x
