#ifndef HELIOS_UTILS_H
#define HELIOS_UTILS_H

#include "json.hpp"
#include <random>
#include <string>
#include <type_traits>

using json = nlohmann::json;

// Template function to sample values from JSON parameter specifications
template<typename T>
T sampleValue(const json& param, std::mt19937& rng) {
    std::string sampling = param["sampling"];
    
    if (sampling == "constant") {
        return static_cast<T>(param["value"]);
    }
    else if (sampling == "uniform") {
        T min_val = param["min"];
        T max_val = param["max"];
        if constexpr (std::is_integral_v<T>) {
            std::uniform_int_distribution<T> dist(min_val, max_val);
            return dist(rng);
        } else {
            std::uniform_real_distribution<T> dist(min_val, max_val);
            return dist(rng);
        }
    }
    else if (sampling == "normal") {
        T mean = param["mean"];
        T stddev = param["stddev"];
        std::normal_distribution<double> dist(static_cast<double>(mean), static_cast<double>(stddev));
        return static_cast<T>(dist(rng));
    }
    else if (sampling == "discrete") {
        auto values = param["values"];
        if (values.is_array() && !values.empty()) {
            std::uniform_int_distribution<size_t> dist(0, values.size() - 1);
            size_t index = dist(rng);
            return static_cast<T>(values[index]);
        }
    }
    
    // fallback - if no valid sampling method or parameters
    if (param.contains("min")) {
        return static_cast<T>(param["min"]);
    } else if (param.contains("value")) {
        return static_cast<T>(param["value"]);
    }
    return T{}; // default value
}

// Forward declarations for Helios types
namespace helios {
    class Context;
}

// Forward declaration for CommandLineOptions (defined in main.h)
struct CommandLineOptions;


// Function declarations for JSON parameter handling
json loadParametersFromJson(const std::string& filename);
void addSampledValues(json& j, std::mt19937& rng);
json sampleParams(json &j_input, std::mt19937 &rng);
json sampleParametersToJson(int crop_index, const json &json_params, std::mt19937 &rng);


// MIN and MAX macros
#ifndef MIN
#define MIN(a, b) ((a) < (b) ? (a) : (b))
#endif

#ifndef MAX
#define MAX(a, b) ((a) > (b) ? (a) : (b))
#endif

#endif // HELIOS_UTILS_H