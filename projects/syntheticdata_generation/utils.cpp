#include "utils.h"
#include "main.h"
#include "Context.h"
#include "yaml-cpp/yaml.h"
#include <fstream>
#include <cstdio>
#include <cstdlib>
#include <stdexcept>
#include <iostream>
#include <limits>  // For std::numeric_limits

using namespace helios;

double round_4digit(double value) {
    return std::round(static_cast<double>(value) * 10000.0) / 10000.0;
}


// Function to load and parse JSON parameters
json loadParametersFromJson(const std::string& filename) {
    std::ifstream file(filename);
    if (!file.is_open()) {
        throw std::runtime_error("Could not open parameters file: " + filename);
    }

    json params;
    file >> params;
    return params;
}

// Template function to sample from distribution based on type
template<typename T>
T sampleFromDistribution(const std::string& distribution_type, 
                         const json& params, 
                         std::mt19937& rng) {
    if (distribution_type == "constant") {
        return static_cast<T>(params["value"]);
    }
    else if (distribution_type == "uniform") {
        T min_val = params["min"];
        T max_val = params["max"];
        if constexpr (std::is_integral_v<T>) {
            std::uniform_int_distribution<T> dist(min_val, max_val);
            return dist(rng);
        } else {
            std::uniform_real_distribution<T> dist(min_val, max_val);
            return dist(rng);
        }
    }
    else if (distribution_type == "normal") {
        float mean = params["mean"];
        float std_dev = params["std"];
        std::normal_distribution<float> dist(mean, std_dev);
        return static_cast<T>(dist(rng));
    }
    else if (distribution_type == "categorical") {
        auto values = params["values"];
        if (values.is_array() && !values.empty()) {
            std::uniform_int_distribution<size_t> dist(0, values.size() - 1);
            size_t index = dist(rng);
            return static_cast<T>(values[index]);
        }
    }
    
    // Fallback
    return T{};
}

// Recursively find all parameters with "distribution" key and replace with sampled value
void addSampledValues(json& j, std::mt19937& rng) {
    if (j.is_object()) {
        // Check if this object has a "distribution" key
        if (j.contains("distribution")) {            
            auto j_distribution = j["distribution"];
            auto j_distribution_params = j_distribution["params"];
            
            std::string distribution_type = j_distribution["type"];
            
            // Handle categorical distribution separately (returns string)
            if (distribution_type == "categorical") {
                // Categorical uses "categories" key, not "values"
                if (j_distribution_params.contains("categories")) {
                    auto categories = j_distribution_params["categories"];
                    if (categories.is_array() && !categories.empty()) {
                        std::uniform_int_distribution<size_t> dist(0, categories.size() - 1);
                        size_t index = dist(rng);
                        j = categories[index];  // Assign the selected category string
                    } else {
                        // Empty categories array - set to empty string as fallback
                        j = "";
                    }
                } else {
                    // No categories key - set to empty string as fallback
                    j = "";
                }
            } else {
                // Type inference: check if parameters suggest integer or float
                bool is_integer = false;
                if (j_distribution_params.contains("min") && j_distribution_params.contains("max")) {
                    is_integer = j_distribution_params["min"].is_number_integer() && 
                                j_distribution_params["max"].is_number_integer();
                } else if (j_distribution_params.contains("value")) {
                    is_integer = j_distribution_params["value"].is_number_integer();
                }
                
                // Sample based on inferred type
                if (is_integer) {
                    j = sampleFromDistribution<int>(distribution_type, j_distribution_params, rng);
                } else {
                    float sampled_value = sampleFromDistribution<float>(distribution_type, j_distribution_params, rng);
                    // Round to 4 decimal places using double precision to avoid artifacts
                    double rounded_value = round_4digit(sampled_value);
                    j = rounded_value;
                }
            }
        } else {
            // Recursively process all nested objects
            for (auto& [key, value] : j.items()) {
                addSampledValues(value, rng);
            }
        }
    }
    else if (j.is_array()) {
        // Process each element in the array
        for (auto& element : j) {
            addSampledValues(element, rng);
        }
    }
}

// Sample all parameters in JSON structure
json sampleParams(json& j_input, std::mt19937& rng) {
    // Recursively add "sampled" values to all parameters
    // But the problem here is some keys need to be sampled, but some are already determined
    // Final json will only have determined value without min, max, sampling, sampled keys
    // Another problem is it don't force the types, such as float and uint
    
    // Create a copy of the json
    json j = j_input;

    // Add sampled values
    addSampledValues(j, rng);

    // Return copied json object
    return j;
}


// Function to compute bounding box and extent for a vector of UUIDs
void getBoundingBoxAndExtent(helios::Context& context, const std::vector<uint>& UUIDs, 
                             vec3& min_corner, vec3& max_corner, 
                             vec3& extent) {
    if (UUIDs.empty()) {
        // Handle empty case (set defaults or throw error)
        min_corner = make_vec3(0, 0, 0);
        max_corner = make_vec3(0, 0, 0);
        extent = make_vec3(0, 0, 0);
        return;
    }

    // Initialize with extreme values
    float min_x = std::numeric_limits<float>::max();
    float min_y = std::numeric_limits<float>::max();
    float min_z = std::numeric_limits<float>::max();
    float max_x = std::numeric_limits<float>::lowest();
    float max_y = std::numeric_limits<float>::lowest();
    float max_z = std::numeric_limits<float>::lowest();

    // Iterate through each UUID and update min/max
    for (uint uuid : UUIDs) {
        vec3 min_c, max_c;
        // std::vector<uint> uuids_plant = context.getObjectPrimitiveUUIDs(uuid);
        context.getPrimitiveBoundingBox(uuid, min_c, max_c);
        min_x = std::min(min_x, min_c.x);
        min_y = std::min(min_y, min_c.y);
        min_z = std::min(min_z, min_c.z);
        max_x = std::max(max_x, max_c.x);
        max_y = std::max(max_y, max_c.y);
        max_z = std::max(max_z, max_c.z);
    }

    // Set output bounding box corners
    min_corner = make_vec3(min_x, min_y, min_z);
    max_corner = make_vec3(max_x, max_y, max_z);

    // Compute extent (size in each dimension)
    extent = max_corner - min_corner;
}

// Function to rescale a set of UUIDs to a specific target extent
void rescaleUUIDsToSize(helios::Context& context, const std::vector<uint>& UUIDs, const vec3& target_extent) {
    if (UUIDs.empty()) {
        return;  // Nothing to scale
    }

    // Get current bounding box and extent
    vec3 min_corner, max_corner, current_extent;
    getBoundingBoxAndExtent(context, UUIDs, min_corner, max_corner, current_extent);

    // Compute scale factors (avoid division by zero)
    vec3 scale = make_vec3(
        (current_extent.x > 0) ? (target_extent.x / current_extent.x) : 1.0f,
        (current_extent.y > 0) ? (target_extent.y / current_extent.y) : 1.0f,
        (current_extent.z > 0) ? (target_extent.z / current_extent.z) : 1.0f
    );

    // Apply scaling
    context.scalePrimitive(UUIDs, scale);
}

// Convert HFOV (degrees) to VFOV (degrees) given aspect ratio (width/height)
float HFOVtoVFOV(float HFOV_deg, float aspect_ratio) {
    if (aspect_ratio <= 0.0f) return HFOV_deg; // fallback
    const float PI = 3.14159265358979323846f;
    auto deg2rad = [&](float d){ return d * (PI/180.0f); };
    auto rad2deg = [&](float r){ return r * (180.0f/PI); };

    float hf_rad = deg2rad(HFOV_deg);
    float tan_h2 = tanf(hf_rad * 0.5f);
    float tan_v2 = tan_h2 / aspect_ratio;
    float vf_rad = 2.0f * atanf(tan_v2);
    return rad2deg(vf_rad);
}

// Convert HFOV (degrees) to diagonal FOV (degrees) given aspect ratio (width/height)
float HFOVtoDFOV(float HFOV_deg, float aspect_ratio) {
    if (aspect_ratio <= 0.0f) return HFOV_deg; // fallback
    const float PI = 3.14159265358979323846f;
    auto deg2rad = [&](float d){ return d * (PI/180.0f); };
    auto rad2deg = [&](float r){ return r * (180.0f/PI); };

    float hf_rad = deg2rad(HFOV_deg);
    float tan_h2 = tanf(hf_rad * 0.5f);
    // diagonal half-angle tangent = sqrt(tan_h2^2 + tan_v2^2)
    float tan_v2 = tan_h2 / aspect_ratio;
    float tan_d2 = sqrtf(tan_h2 * tan_h2 + tan_v2 * tan_v2);
    float df_rad = 2.0f * atanf(tan_d2);
    return rad2deg(df_rad);
}

float calculateFOV(float visible_length, float camera_height) {
    float FOV_rad = 2.0 * atan(visible_length / camera_height / 2.0f);
    return rad2deg(FOV_rad);
}

bool getJsonBoolOr(const json& root,
                  std::initializer_list<const char*> keys,
                  bool default_value) {
    const json* current = &root;
    for (const char* key : keys) {
        std::cout << "[DEBUG] getJsonBoolOr checking key: " << key << std::endl;
        if (!current->is_object() || !current->contains(key)) {
            return default_value;
        }
        current = &(current->at(key));
    }

    if (current->is_null()) {
        return default_value;
    }
    if (current->is_boolean()) {
        return current->get<bool>();
    }
    if (current->is_number_integer()) {
        return current->get<int>() != 0;
    }
    return default_value;
}

std::string getJsonStringOr(const json& root,
                           std::initializer_list<const char*> keys,
                           const std::string& default_value) {
    const json* current = &root;
    for (const char* key : keys) {
        std::cout << "[DEBUG] getJsonStringOr checking key: " << key << std::endl;
        if (!current->is_object() || !current->contains(key)) {
            return default_value;
        }
        current = &(current->at(key));
    }

    if (current->is_null() || !current->is_string()) {
        return default_value;
    }
    return current->get<std::string>();
}