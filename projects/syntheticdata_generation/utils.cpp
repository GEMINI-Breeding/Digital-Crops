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

// Recursively find all parameters with "sampling" key and add "sampled" value
void addSampledValues(json& j, std::mt19937& rng) {
    if (j.is_object()) {
        // Check if this object has a "sampling" key
        if (j.contains("sampling")) {
            std::string sampling = j["sampling"];
            
            // Determine the type and sample accordingly
            if (sampling == "constant") {
                j["sampled"] = j["value"];
            }
            else if (sampling == "uniform") {
                // Try to determine if it's int or float based on the values
                if (j["min"].is_number_integer() && j["max"].is_number_integer()) {
                    j["sampled"] = sampleValue<int>(j, rng);
                } else {
                    j["sampled"] = sampleValue<float>(j, rng);
                }
            }
            else if (sampling == "normal") {
                j["sampled"] = sampleValue<float>(j, rng);
            }
            else if (sampling == "discrete") {
                auto values = j["values"];
                if (values.is_array() && !values.empty()) {
                    std::uniform_int_distribution<size_t> dist(0, values.size() - 1);
                    size_t index = dist(rng);
                    j["sampled"] = values[index];
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

// Recursively find all parameters with "sampling" key and add "sampled" value
json sampleParams(json& j_input, std::mt19937& rng) {
    // Create a copy of the json
    json j = j_input;

    // Add sampled values
    addSampledValues(j, rng);

    // Return copied json object
    return j;
}

// Sample parameters from JSON by adding "sampled" values to the original structure
json sampleParametersToJson(int crop_index, const json& json_params, std::mt19937& rng) {
    // Create a copy of the params for this specific crop
    json params_copy = json_params;
    
    // Select the specific crop
    if (params_copy.contains("plants") && 
        params_copy["plants"].contains("crops") && 
        params_copy["plants"]["crops"].is_array() &&
        crop_index < params_copy["plants"]["crops"].size()) {
        
        // Keep only the selected crop
        json selected_crop = params_copy["plants"]["crops"][crop_index];
        params_copy["plants"]["crops"] = json::array({selected_crop});
    }
    
    // Recursively add sampled values to all parameters with "sampling" key
    addSampledValues(params_copy, rng);
    
    return params_copy;
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


