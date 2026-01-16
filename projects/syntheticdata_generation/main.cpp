#include <algorithm>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <random>
#include <sstream>

#include "CanopyGenerator.h"
#include "LeafOptics.h"
#include "PlantArchitecture.h"
#include "RadiationModel.h"
#include "SolarPosition.h"
#include "SyntheticAnnotation.h"
#include "Visualizer.h"
#include "json.hpp"
// #include "EnergyBalanceModel.h"

#include "field.h"
#include "main.h"
#include "utils.h"
#include "yaml-cpp/yaml.h"

using namespace helios;
namespace fs = std::filesystem;

// Global debug flag definition
bool g_debug_mode = false;

// Camera setup structure to bundle related parameters
struct CameraSetup {
    CameraProperties cam_prop;
    vec3 camera_position;
    vec3 camera_lookat;
    SphericalCoord sun_dir;
};

void init_plant_architecture(PlantArchitecture& plantarchitecture,
                             json sampled_params) {

    // Load plant from Helios Library
    plantarchitecture.loadPlantModelFromLibrary(sampled_params["field"]["plant_type"]);

    // Get the shoot parameters
    std::map<std::string, ShootParameters> shoot_params =
        plantarchitecture.getCurrentShootParameters();

    // update leaf pitch and peduncle length
    shoot_params.at("trifoliate").phytomer_parameters.leaf.pitch    \
     = sampled_params["plantarchitecture"]["phytomer_parameters"]["leaf_pitch"];
    shoot_params.at("trifoliate").flower_bud_break_probability      \
     = sampled_params["plantarchitecture"]["flower_bud_break_probability"];


    // update leaf (comment out  below to render faster)
#if 0
    shoot_params.at("trifoliate")
        .phytomer_parameters.leaf.prototype.prototype_function =
        CowpeaLeafPrototype_trifoliate_OBJ;
#endif

    // apply updated parameters
    plantarchitecture.updateCurrentShootParameters(
        "trifoliate", shoot_params.at("trifoliate"));

    // enable object data output for flower state identification
    plantarchitecture.optionalOutputObjectData("closedflowerID");
    plantarchitecture.optionalOutputObjectData("openflowerID");

}

CameraSetup init_camera(Context& context, PlantArchitecture &plantarchitecture, json sampled_params) {
    CameraSetup setup;
    
    // camera params
    json cam_prop_json = sampled_params["cameraproperties"];
    
    // focus on center of scene
    setup.cam_prop.focal_plane_distance =
        cam_prop_json["camera_height"].get<float>() -
        cam_prop_json["focal_plane_distance_difference"].get<float>(); 

    // make it small so it will be in focus
    setup.cam_prop.lens_diameter =
        cam_prop_json["lens_diameter"].get<float>(); 

    setup.cam_prop.HFOV = cam_prop_json["HFOV"].get<float>();
    setup.cam_prop.camera_resolution = make_int2(
        cam_prop_json["camera_resolution_x"].get<int>(),
        cam_prop_json["camera_resolution_y"].get<int>());

    // setup.cam_prop.FOV_aspect_ratio =
    //     float(setup.cam_prop.camera_resolution.x) /
    //     float(setup.cam_prop.camera_resolution.y);
    // Calculate plant canopy center based on plant base positions or default to origin
    vec3 canopy_center = make_vec3(0, 0, 0);
    if (cam_prop_json["camera_positioning"]["center_plants"]) {
        // Get bounding box from plant base positions for more accurate centering
        vec3 min_corner = make_vec3(std::numeric_limits<float>::max(), 
                                    std::numeric_limits<float>::max(), 
                                    std::numeric_limits<float>::max());
        vec3 max_corner = make_vec3(std::numeric_limits<float>::lowest(), 
                                    std::numeric_limits<float>::lowest(), 
                                    std::numeric_limits<float>::lowest());
        
        // Iterate through all plants and get their base positions
        std::vector<uint> plant_ids = plantarchitecture.getAllPlantIDs();
        for (uint plantID : plant_ids) {
            vec3 plant_position = plantarchitecture.getPlantBasePosition(plantID);
            
            // Update bounding box
            min_corner.x = std::min(min_corner.x, plant_position.x);
            min_corner.y = std::min(min_corner.y, plant_position.y);
            min_corner.z = std::min(min_corner.z, plant_position.z);
            
            max_corner.x = std::max(max_corner.x, plant_position.x);
            max_corner.y = std::max(max_corner.y, plant_position.y);
            max_corner.z = std::max(max_corner.z, plant_position.z);
        }
        
        // Calculate center from bounding box
        canopy_center = (min_corner + max_corner) * 0.5f;
    }

    // Convert azimuth angle from degrees to radians
    float azimuth_rad =
        deg2rad(cam_prop_json["camera_positioning"]
                              ["azimuth_angle"]
                                  .get<float>());
                                // Assuming looking the x axis direction
                                // towards zero when azimuth_angle=0

    // Calculate camera position based on plant canopy center
    float dist = cam_prop_json["camera_positioning"]
                                      ["distance_from_center"]
                                          .get<float>();
    
    // Camear rotation starts at -pi / 2 to see y axis up when rad = 0
    // cos(theta - pi/2) = sin(theta), sin(theta - pi/2) = -cos(theta)
    setup.camera_position.x = canopy_center.x + dist*sin(azimuth_rad); 
    setup.camera_position.y = canopy_center.y - dist*cos(azimuth_rad);
    setup.camera_position.z =
        cam_prop_json["camera_height"]
            .get<float>();

    // Calculate camera lookat point (slightly offset from canopy center)
    setup.camera_lookat.x = canopy_center.x + cam_prop_json["camera_positioning"]
                        ["lookat_offset_x"].get<float>();
    setup.camera_lookat.y = canopy_center.y + cam_prop_json["camera_positioning"]
                        ["lookat_offset_y"].get<float>();
    setup.camera_lookat.z = canopy_center.z + cam_prop_json["camera_positioning"]
                        ["lookat_offset_z"].get<float>();

    setup.sun_dir = make_SphericalCoord(
        deg2rad(sampled_params["sun_position"]["elevation_degrees"]
                    .get<float>()),
        -deg2rad(sampled_params["sun_position"]["azimuth_degrees"]
                     .get<float>()));
    
    return setup;
}


void init_radiation_model(Context &context,
                          RadiationModel &radiation,
                          PlantArchitecture &plantarchitecture,
                          LeafOptics& leafoptics,
                          const CameraSetup& camera_setup,
                          json sampled_params,
                          std::vector<uint> UUIDs_ground) {

    if (g_debug_mode) std::cout << "[DEBUG] Loading radiation XML files..." << std::endl;
    auto radiation_cfg = sampled_params["radiationmodel"];
    // load color and reflectivity data
    context.loadXML(radiation_cfg["colorboard"].get<std::string>().c_str(),
                    true);
    context.loadXML(radiation_cfg["leaf_surface_spectral_data"]["file"]
                        .get<std::string>()
                        .c_str(),
                    true);
    context.loadXML(radiation_cfg["soil_surface_spectral_data"]["file"]
                        .get<std::string>()
                        .c_str(),
                    true);
    context.renameGlobalData("ColorReference_DGK_08", "spectrum_yellow");
    context.renameGlobalData("ColorReference_DGK_09", "spectrum_green");
    context.renameGlobalData("ColorReference_DGK_16", "spectrum_purple");
    context.renameGlobalData("ColorReference_DGK_01", "spectrum_white");
    if (g_debug_mode) std::cout << "[DEBUG] Preparing spectral blends..." << std::endl;

    // prepare custom flower colors
    radiation.blendSpectra("reflectivity_flower_cowpea_closed",
                           {"spectrum_yellow", "spectrum_green"}, {0.35, 0.65});
    radiation.blendSpectra("reflectivity_flower_cowpea_open",
                           {"spectrum_purple", "spectrum_white"},
                           {0.10, 0.90}); // mostly white with purple tint

    // prepare custom pod colors
    radiation.blendSpectra("reflectivity_pod_cowpea",
                           {"spectrum_yellow", "spectrum_green"}, {0.95, 0.05});

    DEBUG_PRINT();

    if (g_debug_mode) std::cout << "[DEBUG] Setting plant spectral properties..." << std::endl;
    // Set default color for whole plant
    std::vector<uint> UUIDs_plants = plantarchitecture.getAllUUIDs();
    context.setPrimitiveData(
        UUIDs_plants, "reflectivity_spectrum",
        radiation_cfg["leaf_surface_spectral_data"]
                      ["reflectivity"]
                          .get<std::string>());
    context.setPrimitiveData(
        UUIDs_plants, "transmissivity_spectrum",
        radiation_cfg["leaf_surface_spectral_data"]
                      ["transmissivity"]
                          .get<std::string>());

    // Set default color for soil
    context.setPrimitiveData(
        UUIDs_ground, "reflectivity_spectrum",
        radiation_cfg["soil_surface_spectral_data"]
                      ["reflectivity"]
                          .get<std::string>());
    // Make the ground plane single-sided (only visible from above)
    context.setPrimitiveData(UUIDs_ground, "twosided_flag", 0u);

    // Specular reflection causes a surface to look "shiny"
    context.setPrimitiveData(UUIDs_plants, "specular_exponent", 10.f);
    context.setPrimitiveData(UUIDs_ground, "specular_exponent", 10.f);

    
    // Initialize leaf optics properties
    LeafOpticsProperties leafopticsprops;
    leafopticsprops.chlorophyllcontent =
        sampled_params["leafoptics"]["chlorophyll_content"].get<int>();
    
    if (g_debug_mode) std::cout << "[DEBUG] Processing individual plants..." << std::endl;
    // Get plantarchitecture plant ids
    std::vector<uint> plant_ids = plantarchitecture.getAllPlantIDs();
    for (uint &id : plant_ids) {

        // label plants
        std::vector<uint> single_plant_UUIDs = plantarchitecture.getAllPlantObjectIDs(id);
        std::vector<uint> uuids_plant = context.getObjectPrimitiveUUIDs(single_plant_UUIDs);
        context.setPrimitiveData(uuids_plant, "plant", id);

        // Get flower obj id in plantarchitecture
        std::vector<uint> flower_obj_ids =
            plantarchitecture.getPlantFlowerObjectIDs(id);

        for (uint &flower_obj_id : flower_obj_ids) {
            std::vector<uint> uuids_flower =
                context.getObjectPrimitiveUUIDs(flower_obj_id);

            // check if flower is open or closed based on object data
            if (context.doesObjectDataExist(flower_obj_id, "closedflowerID")) {
                context.setPrimitiveData(uuids_flower, "reflectivity_spectrum",
                                         "reflectivity_flower_cowpea_closed");
            } else if (context.doesObjectDataExist(flower_obj_id, "openflowerID")) {
                context.setPrimitiveData(uuids_flower, "reflectivity_spectrum",
                                         "reflectivity_flower_cowpea_open"); 
            } else {
                // Default open flower
                context.setPrimitiveData(uuids_flower, "reflectivity_spectrum",
                                         "reflectivity_flower_cowpea_closed");
            }
            
            // label flowers
            context.setPrimitiveData(uuids_flower, "flower", flower_obj_id);
        }

        // Get pod obj id in plantarchitecture
        std::vector<uint> pod_obj_ids =
            plantarchitecture.getPlantFruitObjectIDs(id);
        for (uint& pod_obj_id : pod_obj_ids) {
            std::vector<uint> uuids_pod =
            context.getObjectPrimitiveUUIDs(pod_obj_id);
            // pod coloring
            context.setPrimitiveData(uuids_pod, "reflectivity_spectrum",
                                         "reflectivity_pod_cowpea"); 
            // pod labeling
            context.setPrimitiveData(uuids_pod, "pod", pod_obj_id);
        }

        // Update leaf optical properties
        std::vector<uint> leaf_obj_ids =
            plantarchitecture.getPlantLeafObjectIDs(id);
        for (uint &leaf_obj_id : leaf_obj_ids) {
            std::vector<uint> uuids_leaf =
                context.getObjectPrimitiveUUIDs(leaf_obj_id);
            leafoptics.run(uuids_leaf, leafopticsprops, "cowpea_leaf");
            context.setPrimitiveData(uuids_leaf, "specular_exponent", 10.f);
        }

    }
    
    if (g_debug_mode) std::cout << "[DEBUG] Adding sun and radiation bands..." << std::endl;
    // set up sun lighting
    uint sunID = radiation.addSunSphereRadiationSource(camera_setup.sun_dir);
    radiation.setSourceSpectrum(sunID, "solar_spectrum_direct_ASTMG173");

    // create RGB radiation bands
    radiation.addRadiationBand("red");
    radiation.disableEmission("red");
    radiation.setDiffuseRadiationExtinctionCoeff("red", 0.3f, camera_setup.sun_dir);
    radiation.setScatteringDepth("red", 3);

    radiation.copyRadiationBand("red", "green");
    radiation.copyRadiationBand("red", "blue");

    std::vector<std::string> bandlabels = {"red", "green", "blue"};
    radiation.setDiffuseSpectrum("solar_spectrum_diffuse_ASTMG173");

    std::string cameralabel = "camera";    

    if (g_debug_mode) std::cout << "[DEBUG] Adding radiation camera..." << std::endl;
    // add the camera to the radiation model
    radiation.addRadiationCamera(cameralabel, bandlabels, camera_setup.camera_position,
                                 camera_setup.camera_lookat, camera_setup.cam_prop, 100);

    // set camera spectral response to simulate iPhone camera
    context.loadXML(
        "plugins/radiation/spectral_data/camera_spectral_library.xml", true);
    std::string camera_type =
        radiation_cfg["camera_spectral_data"]["camera_type"]
            .get<std::string>();
    radiation.setCameraSpectralResponse(cameralabel, "red",
                                        (camera_type + "_red").c_str());
    radiation.setCameraSpectralResponse(cameralabel, "green",
                                        (camera_type + "_green").c_str());
    radiation.setCameraSpectralResponse(cameralabel, "blue",
                                        (camera_type + "_blue").c_str());

    if (g_debug_mode) std::cout << "[DEBUG] Radiation model initialization complete." << std::endl;
    return;
}

// Generation mode enum
enum class GenerationMode { AUTO, MANUAL, UNKNOWN };

// Helper function to parse generation mode from string
inline GenerationMode parseGenerationMode(const std::string &mode_str) {
    if (mode_str == "auto") {
        return GenerationMode::AUTO;
    } else if (mode_str == "manual") {
        return GenerationMode::MANUAL;
    } else {
        return GenerationMode::UNKNOWN;
    }
}

// Command line options structure
struct CommandLineOptions {
    bool rotation_view = false;
    bool grow = false;
    bool debug = false;
    bool save_xml = true;
    bool stats_only = false;
    bool gui = false;
    bool run_radiation = true;  // Run faster if running without radiation?
    bool vis = false; // Skip visualizer image by default
    bool calibrate_color = false; // Add color calibration panel and run auto-calibration
    float height = 1.0f;
    int days = 0;
    unsigned int seed = 0;
    int num_iterations = 1;
    std::string tile_file;
    std::string output_dir;
    std::string output_name;
    std::string params_file;
};


// Function to parse command line arguments
CommandLineOptions parseCommandLineArgs(int argc, char *argv[]) {
    CommandLineOptions options;

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];

        // Boolean flags (no additional argument needed)
        if (arg == "-d" || arg == "--debug") {
            options.debug = true;
            g_debug_mode = true;  // Set global debug flag
        } else if (arg == "-r" || arg == "--rotation") {
            options.rotation_view = true;
        } else if (arg == "-g" || arg == "--grow") {
            options.grow = true;
        } else if (arg == "--xml") {
            options.save_xml = true;
        } else if (arg == "--stats-only") {
            options.stats_only = true;
        } else if (arg == "--vis") {
            options.vis = true;
        } else if (arg == "--gui") {
            options.gui = true;
        } else if (arg == "--help") {
            // Print help message
            std::cout << "Usage: " << argv[0] << " [OPTIONS]\n"
                      << "Options:\n"
                      << "  -r, --rotation           Enable rotation view\n"
                      << "  -g, --grow               Enable grow mode\n"
                      << "  -d, --debug              Enable debug mode\n"
                      << "  --xml                    Save XML output\n"
                      << "  --stats-only             Only output statistics\n"
                      << "  --gui                    Enable GUI interactive mode\n"
                      << "  --radiation true|false   Run radiation model (default: true)\n"
                      << "  --vis                    Save visualizer image (default: true)\n"
                      << "  --calibrate-color true|false  Add color calibration panel and auto-calibrate output image (default: false)\n"
                      << "  -h, --height HEIGHT      Set height value (default: 1.0)\n"
                      << "  -t, --tile FILE          Set tile file path\n"
                      << "  -o, --output DIR         Set output directory (default: from params.json)\n"
                      << "  -f, --file FILE          Set plant param file\n"
                      << "  --days N                 Set number of days (default: 0)\n"
                      << "  -s, --seed N             Set random seed (default: random)\n"
                      << "  -n, --name NAME          Set output name (default: 'plot')\n"
                      << "  -i, --iteration N        Set iterations (default: 0)\n"
                      << "  --help                   Show this help message\n";
            std::exit(0);
        }
        // Options with arguments
        else if (i + 1 < argc) {
            if (arg == "--radiation") {
                std::string radiation_flag = argv[++i];
                if (radiation_flag == "false" || radiation_flag == "0") {
                    options.run_radiation = false;
                } else if (radiation_flag == "true" || radiation_flag == "1") {
                    options.run_radiation = true;
                } else {
                    std::printf("Invalid value for --radiation: %s (use true/false or 1/0)\n", radiation_flag.c_str());
                }
            } else if (arg == "--calibrate-color") {
                std::string cal_flag = argv[++i];
                if (cal_flag == "false" || cal_flag == "0") {
                    options.calibrate_color = false;
                } else if (cal_flag == "true" || cal_flag == "1") {
                    options.calibrate_color = true;
                } else {
                    std::printf("Invalid value for --calibrate-color: %s (use true/false or 1/0)\n", cal_flag.c_str());
                }
            } else if (arg == "-h" || arg == "--height") {
                options.height = std::stof(argv[++i]);
            } else if (arg == "-t" || arg == "--tile") {
                options.tile_file = argv[++i];
            } else if (arg == "-o" || arg == "--output") {
                options.output_dir = argv[++i];
            } else if (arg == "-n" || arg == "--name") {
                options.output_name = argv[++i];
            } else if (arg == "--days") {
                options.days = std::stoi(argv[++i]);
            } else if (arg == "-s" || arg == "--seed") {
                options.seed = static_cast<unsigned int>(std::stoi(argv[++i]));
                std::printf("Seed: %u\n", options.seed);
            } else if (arg == "-i" || arg == "--iteration") {
                options.num_iterations = std::max(std::atoi(argv[++i]), 0);
            } else if (arg == "-f" || arg == "--file") {
                options.params_file = argv[++i];
            } else {
                std::printf("Unknown argument: %s\n", arg.c_str());
                std::printf("Use --help for usage information\n");
            }
        } else {
            std::printf("Unknown argument: %s\n", arg.c_str());
            std::printf("Use --help for usage information\n");
        }
    }

    // Echo parsed arguments
    if (g_debug_mode){
        std::cout << "Parsed command line arguments:" << std::endl;
        std::cout << "  rotation_view: " << (options.rotation_view ? "true" : "false") << std::endl;
        std::cout << "  grow: " << (options.grow ? "true" : "false") << std::endl;
        std::cout << "  debug: " << (options.debug ? "true" : "false") << std::endl;
        std::cout << "  save_xml: " << (options.save_xml ? "true" : "false") << std::endl;
        std::cout << "  stats_only: " << (options.stats_only ? "true" : "false") << std::endl;
        std::cout << "  gui: " << (options.gui ? "true" : "false") << std::endl;
        std::cout << "  run_radiation: " << (options.run_radiation ? "true" : "false") << std::endl;
        std::cout << "  vis: " << (options.vis ? "true" : "false") << std::endl;
        std::cout << "  calibrate_color: " << (options.calibrate_color ? "true" : "false") << std::endl;
        std::cout << "  height: " << options.height << std::endl;
        std::cout << "  days: " << options.days << std::endl;
        std::cout << "  seed: " << options.seed << std::endl;
        std::cout << "  num_iterations: " << options.num_iterations << std::endl;
        std::cout << "  tile_file: '" << options.tile_file << "'" << std::endl;
        std::cout << "  output_dir: '" << options.output_dir << "'" << std::endl;
        std::cout << "  output_name: '" << options.output_name << "'" << std::endl;
        std::cout << "  params_file: '" << options.params_file << "'" << std::endl;
    }

    return options;
}

#define CUDA_CHECK_ERROR() { \
    optix::cudaError_t err = optix::cudaGetLastError(); \
    if (err != optix::cudaSuccess) { \
        std::cerr << "CUDA Error: " << optix::cudaGetErrorString(err) \
                  << " at " << __FILE__ << ":" << __LINE__ << std::endl; \
        exit(EXIT_FAILURE); \
    } \
}

// System RAM monitoring function
inline void printSystemMemoryUsage(const std::string& label = "") {
    if (!g_debug_mode) return;
    
    std::ifstream status_file("/proc/self/status");
    std::string line;
    size_t vmrss = 0, vmsize = 0, vmpeak = 0, vmhwm = 0;
    
    while (std::getline(status_file, line)) {
        if (line.find("VmRSS:") == 0) {
            sscanf(line.c_str(), "VmRSS: %zu", &vmrss);
        } else if (line.find("VmSize:") == 0) {
            sscanf(line.c_str(), "VmSize: %zu", &vmsize);
        } else if (line.find("VmPeak:") == 0) {
            sscanf(line.c_str(), "VmPeak: %zu", &vmpeak);
        } else if (line.find("VmHWM:") == 0) {
            sscanf(line.c_str(), "VmHWM: %zu", &vmhwm);
        }
    }
    
    std::cout << "[DEBUG][System RAM" << (label.empty() ? "" : " - " + label) << "] "
              << "Current RSS: " << vmrss / 1024 << " MB, "
              << "Peak RSS: " << vmhwm / 1024 << " MB, "
              << "Peak VmSize: " << vmpeak / 1024 << " MB" << std::endl;
}

// GPU memory monitoring function
inline void printGPUMemoryUsage(const std::string& label = "") {
    if (!g_debug_mode) return;
    
    size_t free_mem, total_mem;
    optix::cudaMemGetInfo(&free_mem, &total_mem);
    size_t used_mem = total_mem - free_mem;
    
    std::cout << "[DEBUG][GPU Memory" << (label.empty() ? "" : " - " + label) << "] "
              << "Used: " << used_mem / (1024*1024) << " MB, "
              << "Free: " << free_mem / (1024*1024) << " MB, "
              << "Total: " << total_mem / (1024*1024) << " MB"
              << " (" << (used_mem * 100 / total_mem) << "% used)" << std::endl;
}

int main(int argc, char *argv[]) {

    // Parse command-line arguments using dedicated function
    CommandLineOptions args = parseCommandLineArgs(argc, argv);

    // load parameters first to check for seed in JSON
    std::string params_file;
    if (args.params_file.size() > 0) {
        params_file = args.params_file;
    } else {
        params_file = "../params.json";
    }
    std::cout << "Loading " << params_file << std::endl;
    json json_params = loadParametersFromJson(params_file);

    // Determine seed with priority: JSON → command line → random
    unsigned int final_seed;
    std::random_device rd;
    
    if (args.seed != 0) {
        // Command line argument has highest priority
        final_seed = args.seed;
        std::cout << "Using seed from command line: " << final_seed << std::endl;
    } else if (json_params.contains("seed") && json_params["seed"].is_number_integer()) {
        // Check if seed is defined in JSON
        final_seed = json_params["seed"].get<unsigned int>();
        std::cout << "Using seed from JSON config: " << final_seed << std::endl;
    } else {
        // Generate random seed
        final_seed = rd();
        std::cout << "Generated random seed: " << final_seed << std::endl;
    }
    
    // Set up random number generator with final seed
    std::mt19937 rng(final_seed);

    // prepare output dir
    std::string output_dir;
    if (args.output_dir.size() > 0) {
        output_dir = args.output_dir;
    } else {
        output_dir = json_params.value("output_directory", "output");
    }
    // Create output dir
    if (!fs::exists(output_dir)) {
        fs::create_directories(output_dir);
    }
    std::cout << "Output directory: " << output_dir << std::endl;

    // Get output name
    std::string output_name = args.output_name.size() > 0 ? args.output_name : "plot";

    // Save the original parameters once (shared across all crops)
    std::ofstream original_params_file(output_dir + "/original_params.json");
    original_params_file << std::setw(4) << json_params << std::endl;
    original_params_file.close();
    std::cout << "Saved original parameters to: original_params.json"
              << std::endl;

    // number of data samples
    const int num_iterations = args.num_iterations;

    auto field = json_params["field"];
    // Parse generation mode
    GenerationMode mode = GenerationMode::UNKNOWN;
    if (field.contains("mode") && field["mode"].is_string()) {
        mode = parseGenerationMode(field["mode"].get<std::string>());
    }

    // Declare context
    Context context;
    context.seedRandomGenerator(final_seed);
    // Delcare LeafOptics, RadiationModel, and PlantArchitecture
    LeafOptics leafoptics(&context);
    RadiationModel radiation(&context);
    PlantArchitecture plantarchitecture(&context);
    for (int i = 0; i < num_iterations; ++i) {
       
        json sampled_params;

        // filename with zero-padded iteration number
        std::stringstream filename_stream;
        filename_stream << output_name << "_" << std::setw(4) << std::setfill('0') << i;
        std::string filename = filename_stream.str();

        // Notes:
        // Recursively add "sampled" values to all parameters
        // But the problem here is some keys need to be sampled, but some are already determined
        // Final json will only have determined value without min, max, sampling, sampled keys
        // Another problem is it don't force the types, such as float and uint
        // Also num columns vs num beds, numb rows are not consistent
        // plant architecture initialize need to be moved, like auto or manual
        // ground also need to be moved
        // Also manual and auto config are confusing. The final output will only have determied 'crops'
        // In auto mode, use auto config to geneate plots and remove the config
        // In manual mode, use the predefined plots 
        // If double row plant thing in auto mode, it will double the nuber ofplants
        // Changed the field size to populate (or cover) all the plants
        // Changes FOV to cover entire field => Actually FOV is pre-calculated from python
        // Therefore the camera height will be the dominant paramter that makes the camera perelex effect
        // auto_config will be deleted when pythpn geneates it
        // Ran
        sampled_params = sampleParams(json_params, rng);

        // Save the seed value to sampled_params
        sampled_params["seed"] = final_seed;

        // Create multiple plots in a grid pattern
        std::vector<uint> plant_IDs_aging;  // Plants that need aging (built from library, age 0)
        if (mode == GenerationMode::AUTO) {
            // Auto plot generation - Earl
            init_plant_architecture(plantarchitecture, sampled_params);
            auto auto_cfg = sampled_params["field"]["auto_config"];
            // Calculate grid positioning to center all plots
            int num_beds = auto_cfg["num_beds"].get<int>();
            int num_rows = auto_cfg["num_rows"].get<int>();
            float plot_spacing_x =
                auto_cfg["plot_spacing_x"].get<float>();
            float plot_spacing_y =
                auto_cfg["plot_spacing_y"].get<float>();
            float total_plot_width = (num_beds - 1) * plot_spacing_x;
            float total_plot_height = (num_rows - 1) * plot_spacing_y;
            float start_x = -total_plot_width / 2.0f;
            float start_y = -total_plot_height / 2.0f;

            std::cout << "Creating " << num_beds << "x"
                      << num_rows << " plot grid..." << std::endl;

            // Create plants for this plot
            for (int row = 0; row < num_rows; ++row) {
                for (int bed = 0; bed < num_beds; ++bed) {
                    // Calculate position for this plot
                    float plot_x = start_x + bed * plot_spacing_x;
                    float plot_y = start_y + row * plot_spacing_y;

                    std::vector<uint> plot_plant_IDs =
                        plantarchitecture.buildPlantCanopyFromLibrary(
                            make_vec3(plot_x, plot_y, 0),
                            make_vec2(auto_cfg["plant_spacing_x"],
                                      auto_cfg["plant_spacing_y"]),
                            make_int2(auto_cfg["planting_rows"],
                                      auto_cfg["plant_count"]),
                            0);

                    // Add to the aging collection
                    plant_IDs_aging.insert(plant_IDs_aging.end(),
                                         plot_plant_IDs.begin(),
                                         plot_plant_IDs.end());
                }
            }
            // Add num_beds and num_rows to sampled_params["field"]
            sampled_params["field"]["num_beds"] = sampled_params["field"]["auto_config"]["num_beds"];
            sampled_params["field"]["num_rows"] = sampled_params["field"]["auto_config"]["num_rows"];
        } else if (mode == GenerationMode::MANUAL) {
            // Manual plot generation - Heesup
            float plot_width = sampled_params["field"]["plot_shape"]["plot_width"];
            float plot_length = sampled_params["field"]["plot_shape"]["plot_length"];
            // NEED TO UPDATE HEARE - There is no more PLOT, plants only exist
            int num_beds = 0;
            int num_rows = 0;
            int num_plants = 0;
            auto plants = sampled_params["field"]["plants"];
            if (sampled_params["field"].contains("plants") 
                && sampled_params["field"]["plants"].is_array()) {
                num_plants = sampled_params["field"]["plants"].size();
            }

            // Get crop type and convert to lowercase for plant library
            for (int j = 0; j < num_plants; j++) {
                int bed = plants[j]["bed"];
                int row = plants[j]["row"];

                num_beds = std::max(bed, num_beds);
                num_rows = std::max(row, num_rows);

                // Select the specific crop
                json selected_crop = plants[j];
                
                // params.json only have single plant type within plot for now
                init_plant_architecture(plantarchitecture, sampled_params);
                
                // plant count and age can be changed here
                vec3 origin(0, 0, 0);

                float X = selected_crop["x"];
                float Y = selected_crop["y"];
                origin.x = (bed-1) * plot_width;
                origin.y = (row-1) * plot_length;
                // float Z = config["crops"][i]["Z"].as<float>();
                vec3 plant_origin = origin + make_vec3(X, Y, 0);
                
                // Check if xml path is provided and valid
                if (selected_crop.contains("xml") && 
                    selected_crop["xml"].is_string() && 
                    !selected_crop["xml"].get<std::string>().empty()) {
                    // Build plant from XML file (already aged)
                    // It will not use plant origin. It will use base position from the XML
                    std::string xml_path = selected_crop["xml"].get<std::string>();
                    std::vector<uint> plot_plant_IDs;
                    plot_plant_IDs = plantarchitecture.readPlantStructureXML(xml_path, 0);
                    for(int i=0;i < plot_plant_IDs.size();i++) {
                        std::cout << "Loaded plant from XML (ID:" << plot_plant_IDs[i] << "): " << xml_path << std::endl;
                    }
                } else {
                    // Build plant from library (needs aging)
                    uint plantID;
                    plantID = plantarchitecture.buildPlantInstanceFromLibrary(plant_origin, true);
                    plant_IDs_aging.push_back(plantID);
                    std::cout << "Generated plant from library (ID:" << plantID << ")" << std::endl;
                }
            }
            
            // Add num_beds and num_rows to sampled_params["field"]
            sampled_params["field"]["num_beds"] = num_beds;
            sampled_params["field"]["num_rows"] = num_rows;
        } else {
            std::cout << "[WARN] plots mode is not defined or invalid!"
                      << std::endl;
            return 0;
        }

        // Remove auto_config key in manual mode before saving
        if (mode == GenerationMode::MANUAL && sampled_params.contains("field") && 
            sampled_params["field"].contains("auto_config")) {
            sampled_params["field"].erase("auto_config");
        }

        // save sampled parameters
        std::string params_filename = output_dir + "/" + filename + "_params.json";
        std::ofstream params_file(params_filename);
        // params_file << std::scientific << std::setprecision(4) << sampled_params << std::endl;
        // params_file.close();
        params_file << std::setw(4) << sampled_params << std::endl;
        params_file.close();

        std::vector<uint> UUIDs_plants = plantarchitecture.getAllPlantIDs();
        std::cout << "Number of crops: " << UUIDs_plants.size() << std::endl;
        printSystemMemoryUsage("After loading plants");
        printGPUMemoryUsage("After loading plants");

        // create ground - either OBJ-based or tile-based
        std::vector<uint> UUIDs_ground;
        if (sampled_params["field"]["plot_shape"]["use_obj_ground"].get<bool>()) {
            //UUIDs_ground = createObjGround(context, sampled_params);
            UUIDs_ground = make_field(context, sampled_params);
            DEBUG_PRINT("OBJ ground created");
            printSystemMemoryUsage("After creating OBJ ground");
            printGPUMemoryUsage("After creating OBJ ground");
        } else {
            
            // Calculate pixel size on ground based on camera FOV and resolution from params
            auto cam_prop = sampled_params["cameraproperties"];
            float camera_height = cam_prop["camera_height"].get<float>();
            float HFOV = cam_prop["HFOV"].get<float>();
            int camera_res_x = cam_prop["camera_resolution_x"].get<int>();
            int camera_res_y = cam_prop["camera_resolution_y"].get<int>();
            
            float HFOV_rad = deg2rad(HFOV);
            float VFOV = HFOVtoVFOV(HFOV, float(camera_res_x) / float(camera_res_y));
            float VFOV_rad = deg2rad(VFOV);
            
            // Ground coverage in each dimension
            float ground_width_visible = 2.0f * camera_height * tan(HFOV_rad / 2.0f);
            float ground_height_visible = 2.0f * camera_height * tan(VFOV_rad / 2.0f);
            
#if 0
            // load dirt texture with fixed size (original method)
            float ground_x = sampled_params["field"]["plot_shape"]["size_x"];
            float ground_y = sampled_params["field"]["plot_shape"]["size_y"];
#else
            float ground_x = ground_width_visible;
            float ground_y = ground_height_visible;
#endif
            helios::vec3 tile_center = make_vec3(0, 0, 0);
            helios::vec2 tile_size = make_vec2(0.1, 0.1);
            helios::vec2 field_size = make_vec2(ground_x, ground_y);

            // Pixel size on ground
            float pixel_size_x = ground_width_visible / camera_res_x;
            float pixel_size_y = ground_height_visible / camera_res_y;
            float pixel_size = std::max(pixel_size_x, pixel_size_y);
            
            // Set patch size to be smaller than pixel size (half pixel for good sampling)
            float desired_patch_size = pixel_size * 0.5f;
            int subdiv_x = std::max(100, (int)(ground_x / desired_patch_size));
            int subdiv_y = std::max(100, (int)(ground_y / desired_patch_size));

            // Prevent exceeding texture resolution constraints by clamping subdivisions
            // Many bundled textures are ~1024x1024; large subdivision counts can trigger errors.
            const int MAX_SUBDIV_PER_AXIS = 512; // conservative cap to avoid Context::addTile errors
            int clamped_subdiv_x = std::min(subdiv_x, MAX_SUBDIV_PER_AXIS);
            int clamped_subdiv_y = std::min(subdiv_y, MAX_SUBDIV_PER_AXIS);

            if (g_debug_mode || true) {
                std::cout << "[DEBUG] Ground tile subdivision calculation:" << std::endl;
                std::cout << "  Camera height: " << camera_height << " m" << std::endl;
                std::cout << "  Ground visible: " << ground_width_visible << " x " << ground_height_visible << " m" << std::endl;
                std::cout << "  Pixel size on ground: " << pixel_size << " m" << std::endl;
                std::cout << "  Desired patch size: " << desired_patch_size << " m" << std::endl;
                std::cout << "  Subdivision (raw): " << subdiv_x << " x " << subdiv_y << std::endl;
                if (subdiv_x != clamped_subdiv_x || subdiv_y != clamped_subdiv_y) {
                    std::cout << "  Subdivision (clamped): " << clamped_subdiv_x << " x " << clamped_subdiv_y << std::endl;
                }
            }
            // Keep texture repeat tied to visual tiling
            int2 texture_repeat = make_int2(round(ground_x / tile_size.x), round(ground_y / tile_size.y));
            UUIDs_ground = context.addTile(tile_center, field_size,
                                           make_SphericalCoord(0, 0),
                                           make_int2(clamped_subdiv_x, clamped_subdiv_y),
                                           "plugins/visualizer/textures/dirt.jpg",
                                           texture_repeat);
        }

        // Age only plants that were built from library (not from XML)
        if (!plant_IDs_aging.empty()) {
            // plants are planted in a single day -> Age all together
            // Therefore there is no plant_age in plants element
            float plant_age = static_cast<int>(sampled_params["field"]["plant_age"]);
            if (plant_age > 0) {
                plantarchitecture.advanceTime(plant_IDs_aging, plant_age);
                std::cout << "Advanced " << plant_IDs_aging.size() << " plants to age: " << plant_age
                          << " days" << std::endl;
            }
        }


        // Write the plant structure to an XML file
        if (args.save_xml) {
            // Track XML file paths to add to params
            std::vector<std::string> xml_file_paths;
            
            for (int i = 0; i < UUIDs_plants.size(); i++) {
                uint plantID = UUIDs_plants[i];
                // filename with zero-padded plant number
                std::stringstream filename_stream;
                filename_stream << filename << "_plant_" << std::setw(4)
                << std::setfill('0') << i << ".xml";
                std::string xml_file_name = output_dir + "/" + filename_stream.str();
                plantarchitecture.writePlantStructureXML(plantID, xml_file_name);
                xml_file_paths.push_back(xml_file_name);  // Store relative path
            }
            
            // Add XML file paths and plant locations to sampled_params and re-save
            if (!xml_file_paths.empty()) {
                if (mode == GenerationMode::MANUAL && sampled_params["field"].contains("plants") 
                    && sampled_params["field"]["plants"].is_array()) {
                    // For manual mode, add xml path to each crop
                    int num_plants = sampled_params["field"]["plants"].size();
                    for (size_t j = 0; j < xml_file_paths.size() && j < num_plants; j++) {
                        sampled_params["field"]["plants"][j]["xml"] = xml_file_paths[j];
                    }
                } else if (mode == GenerationMode::AUTO) {
                    // For auto mode, create crops array with position and XML data
                    json crops_array = json::array();
                    auto auto_config = sampled_params["field"]["auto_config"];
                    // Get grid parameters used during generation
                    int num_beds = auto_config["num_beds"].get<int>();
                    int num_rows = auto_config["num_rows"].get<int>();
                    float plot_spacing_x = auto_config["plot_spacing_x"].get<float>();
                    float plot_spacing_y = auto_config["plot_spacing_y"].get<float>();
                    float total_plot_width = (num_beds - 1) * plot_spacing_x;
                    float total_plot_height = (num_rows - 1) * plot_spacing_y;
                    float start_x = -total_plot_width / 2.0f;
                    float start_y = -total_plot_height / 2.0f;
                    
                    for (size_t j = 0; j < xml_file_paths.size() && j < UUIDs_plants.size(); j++) {
                        uint plantID = UUIDs_plants[j];
                        vec3 plant_position = plantarchitecture.getPlantBasePosition(plantID);
                        
                        // Calculate which bed and row this plant belongs to based on its position
                        // The plot center positions were: plot_x = start_x + bed * plot_spacing_x
                        //                                plot_y = start_y + row * plot_spacing_y
                        int bed = static_cast<int>(std::round((plant_position.x - start_x) / plot_spacing_x));
                        int row = static_cast<int>(std::round((plant_position.y - start_y) / plot_spacing_y));
                        
                        // Calculate the plot center for this bed/row
                        float plot_center_x = start_x + bed * plot_spacing_x;
                        float plot_center_y = start_y + row * plot_spacing_y;
                        
                        // Calculate position relative to plot center
                        float x_relative = plant_position.x - plot_center_x;
                        float y_relative = plant_position.y - plot_center_y;
                        
                        json crop_info;
                        crop_info["bed"] = bed;
                        crop_info["row"] = row;
                        crop_info["x"] = x_relative;
                        crop_info["y"] = y_relative;
                        crop_info["xml"] = xml_file_paths[j];
                        
                        crops_array.push_back(crop_info);
                    }
                    
                    sampled_params["field"]["plants"] = crops_array;
                } else {
                    // Fallback: add as a top-level array
                    sampled_params["xml_files"] = xml_file_paths;
                }
                
                // Re-save the params file with XML paths
                std::ofstream params_file_update(params_filename);
                params_file_update << std::setw(4) << sampled_params << std::endl;
                params_file_update.close();
                std::cout << "Updated parameters file with XML paths: " << params_filename << std::endl;
            }
        }

        // add color calibration target (only when requested)
        // required for RadiationModel::autoCalibrateCameraImage)
        if (args.calibrate_color) {
            CameraCalibration calibration(&context);
            calibration.addCalibriteColorboard(make_vec3(0, 0.75, 0.001), 0.025);
        }

        // Set camera
        CameraSetup camera_setup = init_camera(context, plantarchitecture, sampled_params);
        CameraProperties cam_prop = camera_setup.cam_prop;
        vec3 camera_position = camera_setup.camera_position;
        vec3 camera_lookat = camera_setup.camera_lookat;
        SphericalCoord sun_dir = camera_setup.sun_dir;

        // Add debug patch
        if (args.debug) {
            // Add a reference object
            vec3 position(0, 0, 0.1);      //(x,y,z) position of patch center
            vec2 size(1, 1);               // length and width of patch
            SphericalCoord coord(1, 0, 0); // r=1, el=0, az=0,
            context.addPatch(position, size, coord, "../img_1x1.png");
        }
        
        // Render the visualizer image to file if enabled via CLI flag
        if (args.vis || args.gui) {
            printGPUMemoryUsage("Before visualizer init");
            Visualizer vis(cam_prop.camera_resolution.x, cam_prop.camera_resolution.y);
            vis.clearGeometry();
            vis.hideWatermark();
            //vis.disableMessages();
            
            // set up sun lighting
            vis.setLightDirection(sphere2cart(sun_dir));
            if (sampled_params["sun_position"].value("shadow", true)) {
                vis.setLightingModel(Visualizer::LIGHTING_PHONG_SHADOWED);
            } else {
                vis.setLightingModel(Visualizer::LIGHTING_PHONG);
            }
            vis.setCameraPosition(camera_position, camera_lookat);
            float FOV_aspect_ratio = cam_prop.camera_resolution.x / float(cam_prop.camera_resolution.y);
            vis.setCameraFieldOfView(
                HFOVtoVFOV(cam_prop.HFOV, FOV_aspect_ratio));
            //vis.plotUpdate(true);
            vis.buildContextGeometry(&context);

            std::string save_path = output_dir + "/" + filename + "_vis.jpeg";
            vis.printWindow(save_path.c_str());

            // // Generate annotations
            // // Declare the Synthetic Annotation class.
            // SyntheticAnnotation annotation(&context);
            // annotation.setCameraPosition(camera_position, camera_lookat);
            // annotation.disableInstanceSegmentation();
            // annotation.enableObjectDetection();
            // // annotation.setWindowSize(800, 800);

            // annotation.labelPrimitives("plants");
            // // // Add labels according to whatever scheme we want.
            // for (int i = 0; i < UUIDs_plants.size(); i++) {
            //     uint plantID = UUIDs_plants[i];
            //     {
            //     // loop over plants
            //     std::vector<uint> IDs_plant = plantarchitecture.getAllPlantUUIDs(plantID);
                
            //     // annotation.labelPrimitives(plantarchitecture.getBranchUUIDs(plantID),
            //     //                            "branches");
            //     // annotation.labelPrimitives(plantarchitecture.getLeafUUIDs(plantID),
            //     //                            "leaves");
            //     // std::vector<std::vector<std::vector<uint>>> fruitUUIDs =
            //     //     canopygenerator.getFruitUUIDs(p);
            //     // if (fruitUUIDs.size() == 1) { // no clusters, only
            //     //     individual fruit for (auto &fruit :
            //     //     fruitUUIDs.front())
            //     //         annotation.labelPrimitives(fruit, "clusters");
            //     // } else if (fruitUUIDs.size() >
            //     //            1) { // fruit contained within cluster - label
            //     //            by
            //     //     cluster for (auto &cluster : fruitUUIDs)
            //     //         annotation.labelPrimitives(flatten(cluster),
            //     //                                    "clusters");
            //     // }
            //     }
            // }
            // // Render the annotations.
            // save_path = output_dir + "/" + filename + "/";
            // std::cout << save_path;
            // annotation.render(save_path.c_str());

            if (args.gui) {
                // plotInteractive for GUI mode
                vis.plotInteractive();
            }
        } else {
            if (g_debug_mode) {
                std::cout << "Skipping visualizer image save for: " << filename
                          << " (save_visualizer=false)" << std::endl;
            }
        }


        // Run radiation model by default true
        if (args.run_radiation) {
            printSystemMemoryUsage("Before radiation init");
            printGPUMemoryUsage("Before radiation init");
            if (g_debug_mode) std::cout << "[DEBUG] Initializing radiation model..." << std::endl;
            // Initialize the radiation model
            init_radiation_model(context, radiation, plantarchitecture,
                                 leafoptics, camera_setup, sampled_params,
                                 UUIDs_ground);
            printSystemMemoryUsage("After radiation init");
            printGPUMemoryUsage("After radiation init");

            std::vector<std::string> bandlabels = {"red", "green", "blue"};
            std::string cameralabel = "camera";

            // update geometry and run radiation model
            if (g_debug_mode) std::cout << "[DEBUG] Updating radiation geometry..." << std::endl;
            radiation.updateGeometry();
            printSystemMemoryUsage("After updateGeometry");
            printGPUMemoryUsage("After updateGeometry");
            printGPUMemoryUsage("After updateGeometry");
            CUDA_CHECK_ERROR();

            if (g_debug_mode) std::cout << "[DEBUG] Running radiation bands..." << std::endl;
            radiation.runBand(bandlabels);
            printGPUMemoryUsage("After runBand");

            // process image using standard pipeline
            radiation.applyCameraImageCorrections(cameralabel, "red", "green",
                                                   "blue");

            // save rendered RGB image with custom filename
            std::string image_file = radiation.writeCameraImage(
                cameralabel, bandlabels, "RGB", output_dir, 0);

            // move image_file to output_dir/<filename>.jpeg
            try {
                std::string target_path = output_dir + "/" + filename + ".jpeg";
                if (image_file != target_path) {
                    fs::path src(image_file);
                    fs::path dst(target_path);
                    // try rename (move)
                    try {
                        fs::rename(src, dst);
                    } catch (const fs::filesystem_error &e) {
                        // fallback to copy + remove if rename fails (e.g., across filesystems)
                        fs::copy_file(src, dst, fs::copy_options::overwrite_existing);
                        fs::remove(src);
                    }
                    image_file = target_path; // update to moved path
                }
            } catch (const std::exception &e) {
                std::cerr << "Warning: failed to move image file: " << e.what() << std::endl;
            }
    

            // Export bounding boxes and segmentation masks in COCO format
            radiation.writeImageBoundingBoxes(cameralabel, {"plant", "flower", "pod"},
                                              {0, 1, 2}, image_file, "classes.txt",
                                              output_dir + '/');

            radiation.writeImageSegmentationMasks(
                cameralabel, {"plant", "flower", "pod"}, {0, 1, 2},
                output_dir + '/' + filename + "_labels.json", image_file);

            // auto-calibrate camera using colorboard reference values with
            // quality report (only if user enabled calibration)
            std::string corrected_image;
            if (args.calibrate_color) {
                corrected_image = radiation.autoCalibrateCameraImage(
                    cameralabel, "red", "green", "blue",
                    output_dir + '/' + filename + ".jpeg", true);
            }

            // Export camera parameters
            // radiation.setCameraMetadata()
            // radiation.writeCameraMetadataFile(cameralabel, output_dir + '/' + filename + "_camera.json");
        }
    }

    std::cout << "\nCompleted all " << num_iterations
              << " iterations. Parameters saved to individual JSON files."
              << std::endl;

     return 0;
}