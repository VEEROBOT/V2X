/**
 * File: udp_client.cpp
 * Module: V2X Authentication Testbed — OBU UDP Client
 *
 * Purpose:
 *    UDP communication layer for OBU to RSU. Sends authentication packets
 *    and receives responses over connectionless UDP socket.
 *
 * Author(s): Praveen Kumar
 * Company: Siliris Technologies Pvt. Ltd
 * Created: 15th February 2026
 * Version: 1.1
 *
 * Key Responsibilities:
 *    - Create UDP socket
 *    - Send AuthRequest packets to RSU
 *    - Receive AuthResponse and confirmation packets
 *    - Handle socket timeouts and errors
 *    - Provide synchronous send/receive interface
 *
 * License:
 *    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
 *    Proprietary - See LICENSE file for terms and conditions.
 */

#include "udp_client.h"

#include <sys/socket.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <poll.h>
#include <cstring>
#include <stdexcept>
#include <iostream>

namespace v2x {

UdpClient::UdpClient(const std::string& bind_ip, int listen_port,
                     const std::string& rsu_ip, int rsu_port)
    : bind_ip_(bind_ip), listen_port_(listen_port),
      rsu_ip_(rsu_ip), rsu_port_(rsu_port), fd_(-1) {}

UdpClient::~UdpClient() {
    close_socket();
}

void UdpClient::open() {
    fd_ = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd_ < 0) throw std::runtime_error("UDP socket() failed");

    int opt = 1;
    setsockopt(fd_, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    struct sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(listen_port_);
    inet_pton(AF_INET, bind_ip_.c_str(), &addr.sin_addr);

    if (bind(fd_, reinterpret_cast<struct sockaddr*>(&addr), sizeof(addr)) < 0) {
        ::close(fd_);
        fd_ = -1;
        throw std::runtime_error("UDP bind() failed on port " +
                                 std::to_string(listen_port_));
    }

    std::cout << "[UDP] Bound to " << bind_ip_ << ":" << listen_port_
              << ", target RSU " << rsu_ip_ << ":" << rsu_port_ << std::endl;
}

void UdpClient::close_socket() {
    if (fd_ >= 0) {
        ::close(fd_);
        fd_ = -1;
    }
}

bool UdpClient::send_to_rsu(const std::vector<uint8_t>& data) {
    struct sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(rsu_port_);
    inet_pton(AF_INET, rsu_ip_.c_str(), &addr.sin_addr);

    ssize_t sent = sendto(fd_, data.data(), data.size(), 0,
                          reinterpret_cast<struct sockaddr*>(&addr),
                          sizeof(addr));
    return (sent == static_cast<ssize_t>(data.size()));
}

std::optional<std::vector<uint8_t>> UdpClient::receive(int timeout_ms) {
    struct pollfd pfd;
    pfd.fd = fd_;
    pfd.events = POLLIN;

    int ret = poll(&pfd, 1, timeout_ms);
    if (ret <= 0) return std::nullopt; // Timeout or error

    std::vector<uint8_t> buf(8192);
    struct sockaddr_in sender{};
    socklen_t slen = sizeof(sender);

    ssize_t n = recvfrom(fd_, buf.data(), buf.size(), 0,
                         reinterpret_cast<struct sockaddr*>(&sender), &slen);
    if (n <= 0) return std::nullopt;

    buf.resize(n);
    return buf;
}

} // namespace v2x
