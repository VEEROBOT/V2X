#pragma once
#include <string>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <map>

namespace v2x {

/**
 * Minimal JSON config reader.
 * Handles flat key-value JSON (no nesting).
 * For a testbed this is sufficient — no need for a JSON library dependency.
 */
class ConfigReader {
public:
    explicit ConfigReader(const std::string& path) {
        std::ifstream f(path);
        if (!f) throw std::runtime_error("Cannot open config: " + path);
        std::stringstream ss;
        ss << f.rdbuf();
        parse(ss.str());
    }

    std::string get_string(const std::string& key, const std::string& def = "") const {
        auto it = values_.find(key);
        return (it != values_.end()) ? it->second : def;
    }

    int get_int(const std::string& key, int def = 0) const {
        auto it = values_.find(key);
        return (it != values_.end()) ? std::stoi(it->second) : def;
    }

    double get_double(const std::string& key, double def = 0.0) const {
        auto it = values_.find(key);
        return (it != values_.end()) ? std::stod(it->second) : def;
    }

    bool get_bool(const std::string& key, bool def = false) const {
        auto it = values_.find(key);
        if (it == values_.end()) return def;
        return (it->second == "true" || it->second == "1");
    }

private:
    std::map<std::string, std::string> values_;

    void parse(const std::string& json) {
        // Simple parser: find "key": "value" or "key": number patterns
        size_t pos = 0;
        while (pos < json.size()) {
            // Find key
            size_t ks = json.find('"', pos);
            if (ks == std::string::npos) break;
            size_t ke = json.find('"', ks + 1);
            if (ke == std::string::npos) break;
            std::string key = json.substr(ks + 1, ke - ks - 1);

            // Find colon
            size_t colon = json.find(':', ke + 1);
            if (colon == std::string::npos) break;

            // Find value (string or number/bool)
            size_t vs = json.find_first_not_of(" \t\n\r", colon + 1);
            if (vs == std::string::npos) break;

            std::string value;
            if (json[vs] == '"') {
                size_t ve = json.find('"', vs + 1);
                value = json.substr(vs + 1, ve - vs - 1);
                pos = ve + 1;
            } else {
                size_t ve = json.find_first_of(",}\n\r", vs);
                value = json.substr(vs, ve - vs);
                // Trim whitespace
                while (!value.empty() && (value.back() == ' ' || value.back() == '\t'))
                    value.pop_back();
                pos = (ve != std::string::npos) ? ve + 1 : json.size();
            }

            values_[key] = value;
        }
    }
};

} // namespace v2x
