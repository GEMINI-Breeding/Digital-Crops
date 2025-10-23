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

// Function to parse command line arguments
CommandLineOptions parseCommandLineArgs(int argc, char* argv[]) {
    CommandLineOptions options;
    
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        
        // Boolean flags (no additional argument needed)
        if (arg == "-d") {
            options.debug = true;
        }else if (arg == "-r") {
            options.rotation_view = true;
        } else if (arg == "-g") {
            options.grow = true;
        } else if (arg == "-fast") {
            options.fast = true;
        } else if (arg == "-xml") {
            options.save_xml = true;
        } else if (arg == "-stats_only") {
            options.stats_only = true;
        }
        // Options with values (requires next argument)
        else if (arg == "-h" && i + 1 < argc) {
            options.height = std::stof(argv[++i]);
        } else if (arg == "-tile" && i + 1 < argc) {
            options.tile_file = argv[++i];
        } else if (arg == "-o" && i + 1 < argc) {
            options.save_dir = argv[++i];
            std::printf("Save dir: %s\n", options.save_dir.c_str());
        } else if (arg == "-f" && i + 1 < argc) {
            options.plant_model_file = argv[++i];
        } else if (arg == "-days" && i + 1 < argc) {
            options.days = std::stoi(argv[++i]);
        } else if (arg == "-seed" && i + 1 < argc) {
            options.seed = static_cast<unsigned int>(std::stoi(argv[++i]));
            std::printf("Seed: %u\n", options.seed);
        } else if (arg == "-name" && i + 1 < argc) {
            options.output_name = argv[++i];
            std::printf("Output name: %s\n", options.output_name.c_str());
        } else if (arg == "--help" || arg == "-help") {
            // Print help message
            std::cout << "Usage: " << argv[0] << " [OPTIONS]\n"
                      << "Options:\n"
                      << "  -r              Enable rotation view\n"
                      << "  -g              Enable grow mode\n"
                      << "  -d              Enable debug mode\n"
                      << "  -xml            Save XML output\n"
                      << "  -stats_only     Only output statistics\n"
                      << "  -h HEIGHT       Set height value\n"
                      << "  -tile FILE      Set tile file path\n"
                      << "  -o DIR          Set output directory\n"
                      << "  -f FILE         Set plant model file\n"
                      << "  -days N         Set number of days\n"
                      << "  -seed N         Set random seed\n"
                      << "  -name NAME      Set output name\n"
                      << "  --help          Show this help message\n";
            std::exit(0);
        } else {
            std::printf("Unknown argument: %s\n", arg.c_str());
            std::printf("Use --help for usage information\n");
        }
    }
    
    return options;
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


