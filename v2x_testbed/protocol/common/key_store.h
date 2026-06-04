#pragma once
#include "crypto/crypto_provider.h"
#include <string>
#include <fstream>
#include <stdexcept>

namespace v2x {

class KeyStore {
public:
    explicit KeyStore(const std::string& key_dir) : dir_(key_dir) {}

    void save(const std::string& name, const Bytes& data) {
        std::string path = dir_ + "/" + name + ".bin";
        std::ofstream f(path, std::ios::binary);
        if (!f) throw std::runtime_error("Cannot write key: " + path);
        uint32_t len = static_cast<uint32_t>(data.size());
        f.write(reinterpret_cast<const char*>(&len), 4);
        f.write(reinterpret_cast<const char*>(data.data()), data.size());
    }

    Bytes load(const std::string& name) {
        std::string path = dir_ + "/" + name + ".bin";
        std::ifstream f(path, std::ios::binary);
        if (!f) throw std::runtime_error("Cannot read key: " + path);
        uint32_t len;
        f.read(reinterpret_cast<char*>(&len), 4);
        Bytes data(len);
        f.read(reinterpret_cast<char*>(data.data()), len);
        return data;
    }

    bool exists(const std::string& name) {
        std::string path = dir_ + "/" + name + ".bin";
        std::ifstream f(path);
        return f.good();
    }

private:
    std::string dir_;
};

} // namespace v2x
