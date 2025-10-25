#include "utils.h"
#include "main.h"
#include "Context.h"
#include "yaml-cpp/yaml.h"
#include <fstream>
#include <cstdio>
#include <cstdlib>
#include <stdexcept>
#include <iostream>

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


