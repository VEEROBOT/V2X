/**
 * File: udp_server.cpp
 * Module: V2X Authentication Testbed — RSU UDP Server
 *
 * Purpose:
 *    UDP server for receiving authentication packets from OBUs on port 5000.
 *    Receives complete packets and dispatches to packet processor.
 *
 * Author(s): Praveen Kumar
 * Company: Siliris Technologies Pvt. Ltd
 * Created: 15th February 2026
 * Version: 1.1
 *
 * Key Responsibilities:
 *    - Create and bind UDP socket
 *    - Receive authentication packets from OBUs
 *    - Extract source IP/port for response routing
 *    - Buffer incoming datagrams
 *    - Provide non-blocking receive interface\n *
 * License:
 *    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
 *    Proprietary - See LICENSE file for terms and conditions.
 */

#include "udp_server.h"

#include <sys/socket.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <cstring>
#include <iostream>

namespace v2x {

UdpServer::UdpServer(const std::string& bind_ip, int port, ReceiveBuffer& buffer)
    : bind_ip_(bind_ip), port_(port), fd_(-1), buffer_(buffer), running_(false) {}

UdpServer::~UdpServer() {
    stop();
}

void UdpServer::start() {
    fd_ = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd_ < 0) throw std::runtime_error("UDP socket() failed");

    // Allow reuse and broadcast (needed for car alert to 192.168.x.255)
    int opt = 1;
    setsockopt(fd_, SOL_SOCKET, SO_REUSEADDR,  &opt, sizeof(opt));
    setsockopt(fd_, SOL_SOCKET, SO_BROADCAST,  &opt, sizeof(opt));

    struct sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port_);
    inet_pton(AF_INET, bind_ip_.c_str(), &addr.sin_addr);

    if (bind(fd_, reinterpret_cast<struct sockaddr*>(&addr), sizeof(addr)) < 0) {
        close(fd_);
        throw std::runtime_error("UDP bind() failed on port " + std::to_string(port_));
    }

    running_ = true;
    thread_ = std::thread(&UdpServer::listen_loop, this);

    std::cout << "[UDP] Listening on " << bind_ip_ << ":" << port_ << std::endl;
}

void UdpServer::stop() {
    running_ = false;
    if (fd_ >= 0) {
        shutdown(fd_, SHUT_RDWR);
        close(fd_);
        fd_ = -1;
    }
    if (thread_.joinable()) thread_.join();
}

void UdpServer::listen_loop() {
    std::vector<uint8_t> buf(8192); // Max UDP packet we expect (~5KB for lattice)

    while (running_) {
        struct sockaddr_in sender_addr{};
        socklen_t sender_len = sizeof(sender_addr);

        ssize_t n = recvfrom(fd_, buf.data(), buf.size(), 0,
                             reinterpret_cast<struct sockaddr*>(&sender_addr),
                             &sender_len);
        if (n <= 0) {
            if (!running_) break;
            continue;
        }

        char ip_str[INET_ADDRSTRLEN];
        inet_ntop(AF_INET, &sender_addr.sin_addr, ip_str, sizeof(ip_str));
        int sender_port = ntohs(sender_addr.sin_port);

        // Copy received data and push to buffer
        std::vector<uint8_t> pkt_data(buf.begin(), buf.begin() + n);
        bool stored = buffer_.push(std::move(pkt_data), ip_str, sender_port);

        if (!stored) {
            // Buffer was full — packet dropped (counted by receive_buffer)
        }
    }
}

bool UdpServer::send_to(const std::vector<uint8_t>& data,
                         const std::string& ip, int port) {
    struct sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    inet_pton(AF_INET, ip.c_str(), &addr.sin_addr);

    ssize_t sent = sendto(fd_, data.data(), data.size(), 0,
                          reinterpret_cast<struct sockaddr*>(&addr),
                          sizeof(addr));
    return (sent == static_cast<ssize_t>(data.size()));
}

} // namespace v2x
