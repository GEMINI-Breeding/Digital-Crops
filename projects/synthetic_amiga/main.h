//
// Created by Heesup Yun on 7/27/23.
//

#ifndef HELIOS_MAIN_H
#define HELIOS_MAIN_H



#include "json.hpp"

#include <random>
#include <string>
#include <type_traits>
#include <vector>

using json = nlohmann::json;

// Forward declarations
namespace helios {
    class Context;
    typedef unsigned int uint;
}

// Command line options structure
struct CommandLineOptions {
    bool rotation_view = false;
    bool grow = false;
    bool debug = false;
    bool save_xml = false;
    bool stats_only = false;
    bool fast = false;  // Run faster by running visualizer only?
    float height = 1.0f;
    int days = 0;
    unsigned int seed = 0;
    int start_iteration = 0;
    std::string tile_file;
    std::string save_dir;
    std::string plant_model_file;
    std::string output_name;
};

// Function to parse command line arguments
CommandLineOptions parseCommandLineArgs(int argc, char* argv[]);

#endif //HELIOS_MAIN_H

