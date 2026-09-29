#ifndef SYN2REAL_CONFIG_H
#define SYN2REAL_CONFIG_H

#include <fstream>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>

//! Flat "key value" configuration.
/** Deliberately not JSON/XML: the optimizer writes these files mechanically and
 *  a human reads them in diffs, so a dependency-free one-pair-per-line format is
 *  the least that does the job. Unknown keys are an error rather than a silent
 *  default, so a typo in a swept parameter fails loudly instead of quietly
 *  rendering the baseline a thousand times. */
class Config {
public:
    void load(const std::string &path) {
        std::ifstream f(path);
        if (!f) throw std::runtime_error("cannot open config: " + path);
        std::string line;
        int lineno = 0;
        while (std::getline(f, line)) {
            lineno++;
            const size_t c = line.find('#');
            if (c != std::string::npos) line = line.substr(0, c);
            std::istringstream ss(line);
            std::string k, v;
            if (!(ss >> k >> v)) continue;
            values_[k] = v;
        }
    }

    void set(const std::string &k, const std::string &v) { values_[k] = v; }

    bool has(const std::string &k) const { return values_.count(k) > 0; }

    float f(const std::string &k) const { return std::stof(need(k)); }
    int i(const std::string &k) const { return std::stoi(need(k)); }
    std::string s(const std::string &k) const { return need(k); }

    float f(const std::string &k, float dflt) const { return has(k) ? std::stof(values_.at(k)) : dflt; }
    int i(const std::string &k, int dflt) const { return has(k) ? std::stoi(values_.at(k)) : dflt; }
    std::string s(const std::string &k, const std::string &dflt) const { return has(k) ? values_.at(k) : dflt; }

    const std::map<std::string, std::string> &all() const { return values_; }

private:
    const std::string &need(const std::string &k) const {
        auto it = values_.find(k);
        if (it == values_.end()) throw std::runtime_error("missing config key: " + k);
        return it->second;
    }
    std::map<std::string, std::string> values_;
};

#endif
