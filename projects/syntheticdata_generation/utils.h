#ifndef HELIOS_UTILS_H
#define HELIOS_UTILS_H

#include "json.hpp"
#include "Context.h"
#include <random>
#include <string>
#include <type_traits>

// using json = nlohmann::json;
using json = nlohmann::ordered_json; // Keeps the JSON key orders

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

// Helper function to get a number from JSON with a default value
template <typename T>
inline T getJsonNumberOr(const json& root,
                         std::initializer_list<const char*> keys,
                         T default_value) {
    const json* current = &root;
    for (const char* key : keys) {
        std::cout << "[DEBUG] getJsonNumberOr checking key: " << key << std::endl;
        if (!current->is_object() || !current->contains(key)) {
            return default_value;
        }
        current = &(current->at(key));
    }

    if (current->is_null() || !current->is_number()) {
        return default_value;
    }
    return current->get<T>();
}

// Helper function to get a boolean from JSON with a default value
bool getJsonBoolOr(const json& root,
                  std::initializer_list<const char*> keys,
                  bool default_value);

// Helper function to get a string from JSON with a default value
std::string getJsonStringOr(const json& root,
                           std::initializer_list<const char*> keys,
                           const std::string& default_value);

// Field-of-view helper functions
// HFOV_deg: horizontal FOV in degrees
// aspect_ratio: width / height
float HFOVtoVFOV(float HFOV_deg, float aspect_ratio);
float HFOVtoDFOV(float HFOV_deg, float aspect_ratio);
float calculateFOV(float visible_length, float camera_height);

// Function to compute bounding box and extent for a vector of UUIDs
void getBoundingBoxAndExtent(helios::Context& context, const std::vector<unsigned int>& UUIDs, 
                             helios::vec3& min_corner, helios::vec3& max_corner, 
                             helios::vec3& extent);

// Function to rescale a set of UUIDs to a specific target extent
void rescaleUUIDsToSize(helios::Context& context, const std::vector<unsigned int>& UUIDs, const helios::vec3& target_extent);

double round_4digit(double value);
// MIN and MAX macros
#ifndef MIN
#define MIN(a, b) ((a) < (b) ? (a) : (b))
#endif

#ifndef MAX
#define MAX(a, b) ((a) > (b) ? (a) : (b))
#endif

#endif // HELIOS_UTILS_H