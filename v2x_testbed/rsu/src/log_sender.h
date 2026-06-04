#pragma once
#include <string>
#include <queue>
#include <mutex>
#include <thread>
#include <atomic>
#include <condition_variable>

namespace v2x {

class LogSender {
public:
    LogSender(const std::string& desktop_ip, int desktop_port);
    ~LogSender();

    /** Queue a JSON event for sending. Thread-safe. */
    void send_event(const std::string& json_event);

    /** Start the sender thread. Connects to Desktop. */
    void start();

    /** Stop the sender thread. */
    void stop();

    bool is_connected() const { return connected_; }

private:
    std::string desktop_ip_;
    int desktop_port_;
    int fd_;
    std::atomic<bool> running_;
    std::atomic<bool> connected_;

    std::queue<std::string> queue_;
    std::mutex mtx_;
    std::condition_variable cv_;
    std::thread thread_;

    void sender_loop();
    bool try_connect();
    bool send_json(const std::string& json);
};

} // namespace v2x
