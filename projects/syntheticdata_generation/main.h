//
// Created by Heesup Yun on 7/27/23.
//

#ifndef HELIOS_MAIN_H
#define HELIOS_MAIN_H

#include <random>
#include <string>
#include <type_traits>
#include <vector>

// Forward declarations
namespace helios {
    class Context;
    typedef unsigned int uint;
}


// Global debug flag
extern bool g_debug_mode;

// Command line options structure
enum class Renderer {
    NONE,       // Do not render any image
    VIS,        // OpenGL visualizer image only
    RADIATION,  // Radiation model camera image only
    ALL         // Both visualizer and radiation model images
};

struct CommandLineOptions {
    bool rotation_view = false;
    bool grow = false;
    bool debug = false;
    bool save_xml = true;       // Save plant structure XML files
    bool stats_only = false;
    bool gui = false;
    Renderer renderer = Renderer::ALL; // Default: render both visualizer and radiation images
    bool calibrate_color = false; // Add color calibration panel and run auto-calibration
    bool dry_run = false; // Load and validate JSON without running generation
    bool run_multispectral = false; // Generate multispectral (NIR) image
    bool run_temperature = false; // Generate temperature (LW) image
    bool run_depth = false; // Generate depth map image
    bool run_wue = false; // Generate Water-Use Efficiency (WUE) image
    int focus_plant = -1; // -1 = use JSON, 0 = disable, 1 = enable auto-fit FOV to plant bounding box + 5% margin
    float height = 0.0f;  // Default empty value 
    float fov = -1.0f; // -1 means "not set" (use auto-calculated value)
    int dap = -1; // -1 means "not set" (use value from JSON)
    unsigned int seed = 0;
    int num_iterations = 1;
    std::string tile_file;
    std::string output_dir;
    std::string output_name;
    std::string params_file;
    std::string plant_type; // Override plant_type from CLI (e.g. cowpea, bean, sorghum, soybean, maize)
    std::string genotype;   // Override genotype archetype (e.g. bush, spreading, vine, dwarf, tall, random)
    std::string input_xml;  // Optional plant XML file to load and render
};

// Debug print macro - expands __FILE__ and __LINE__ at call site
// Usage: DEBUG_PRINT() or DEBUG_PRINT("message")
#define DEBUG_PRINT(...) do { \
    if (g_debug_mode) { \
        printf("%s:%d", __FILE__, __LINE__); \
        if (sizeof(#__VA_ARGS__) > 1) printf(" - " __VA_ARGS__); \
        printf("\n"); \
    } \
} while(0)

#endif //HELIOS_MAIN_H

