#include <algorithm>
#include <cmath>
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

// Helper function to round a float to a specific number of decimal places
inline double roundToPrecision(double value, int precision) {
    double multiplier = std::pow(10.0, precision);
    return std::round(value * multiplier) / multiplier;
}

// Global debug flag definition
bool g_debug_mode = false;

// Camera setup structure to bundle related parameters
struct CameraSetup {
    CameraProperties cam_prop; // See Helios/plugins/radiation/include/RadiationModel.h
    vec3 camera_position;
    vec3 camera_lookat;
    SphericalCoord sun_dir;
};

void init_plant_architecture(PlantArchitecture& plantarchitecture,
                             json sampled_params) {

    // Load plant from Helios Library
    plantarchitecture.loadPlantModelFromLibrary(sampled_params["field"]["plant_type"]);
    plantarchitecture.disableMessages();
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

    float ground_x = sampled_params["field"]["size_x"];
    float camera_height = cam_prop_json["camera_height"].get<float>();
    setup.cam_prop.HFOV = calculateFOV(ground_x, camera_height);

    setup.cam_prop.camera_resolution = make_int2(
        cam_prop_json["camera_resolution_x"].get<int>(),
        cam_prop_json["camera_resolution_y"].get<int>());
    
    // Exposure mode: "auto" (automatic exposure), "ISOXXX" (ISO-based, e.g., "ISO100"), or "manual" (no automatic exposure scaling). ISO mode is calibrated to match auto-exposure at reference settings (ISO 100, 1/125s, f/2.8) for typical Helios
    // scenes.
#if 0
    setup.cam_prop.exposure = "auto"; 
#else
    setup.cam_prop.exposure = "ISO12800"; 
    setup.cam_prop.shutter_speed = 1.0 / 125.0f; 
#endif
    //setup.cam_prop.white_balance = "off";
    //! Camera shutter speed in seconds (used for ISO-based exposure calculations). Example: 1/125 second = 0.008

    // Deprecated - will be automatically updated
    // setup.cam_prop.FOV_aspect_ratio =
    //     float(setup.cam_prop.camera_resolution.x) /
    //     float(setup.cam_prop.camera_resolution.y);

    // Calculate plant canopy center based on plant base positions or default to origin
    vec3 canopy_center = make_vec3(0, 0, 0);
    
    // Check if center_plants key exists and is not null
    bool center_plants = false;
    try {
        if (cam_prop_json.contains("camera_positioning") && 
            cam_prop_json["camera_positioning"].contains("center_plants") &&
            !cam_prop_json["camera_positioning"]["center_plants"].is_null()) {
            center_plants = cam_prop_json["camera_positioning"]["center_plants"].get<bool>();
            std::cout << "[DEBUG] center_plants = " << center_plants << std::endl;
        } else {
            std::cout << "[DEBUG] center_plants key not found or null, using default: false" << std::endl;
        }
    } catch (const std::exception& e) {
        std::cerr << "[ERROR] Failed to read camera_positioning.center_plants: " << e.what() << std::endl;
        std::cerr << "[ERROR] Using default value: false" << std::endl;
    }
    
    if (center_plants) {
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

void update_leafoptics(Context &context,
                        PlantArchitecture &plantarchitecture,
                        LeafOptics& leafoptics,
                        json sampled_params) {
    
    // Extract leaf specular exponent from JSON with default value
    float leaf_specular = sampled_params["leafoptics"].value("specular_exponent", 2.0f);
    
    // Get plantarchitecture plant ids
    std::vector<uint> plant_ids = plantarchitecture.getAllPlantIDs();

    // Set default color for the plant
    std::vector<uint> UUIDs_plants = plantarchitecture.getAllUUIDs();
    context.setPrimitiveData(
        UUIDs_plants, "reflectivity_spectrum","leaf_reflectivity_prospect");
    context.setPrimitiveData(
        UUIDs_plants, "transmissivity_spectrum","leaf_transmissivity_prospect");

    for (uint &id : plant_ids) {
        // label plants
        std::vector<uint> single_plant_UUIDs = plantarchitecture.getAllPlantObjectIDs(id);
        std::vector<uint> uuids_plant = context.getObjectPrimitiveUUIDs(single_plant_UUIDs);
        context.setPrimitiveData(uuids_plant, "plant", id);
        
        // Get flower obj id in plantarchitecture
        // Assign spectrum data and label
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
        // Update peduncle optical properties using PROSPECT-generated spectra
        std::vector<uint> peduncle_obj_ids = plantarchitecture.getPlantPeduncleObjectIDs(id);
        std::vector<uint> uuids_peduncle = context.getObjectPrimitiveUUIDs(peduncle_obj_ids);
        context.setPrimitiveData(uuids_peduncle, "reflectivity_spectrum", "leaf_reflectivity_prospect");
        context.setPrimitiveData(uuids_peduncle, "transmissivity_spectrum", "leaf_transmissivity_prospect");
        context.setPrimitiveData(uuids_peduncle, "specular_exponent", leaf_specular);

    
        // Update internode optical properties using PROSPECT-generated spectra
        std::vector<uint> internode_obj_ids = plantarchitecture.getPlantInternodeObjectIDs(id);
        std::vector<uint> uuids_internode = context.getObjectPrimitiveUUIDs(internode_obj_ids);
        context.setPrimitiveData(uuids_internode, "reflectivity_spectrum", "leaf_reflectivity_prospect");
        context.setPrimitiveData(uuids_internode, "transmissivity_spectrum", "leaf_transmissivity_prospect");
        context.setPrimitiveData(uuids_internode, "specular_exponent", leaf_specular);

        // Update petiole optical properties using PROSPECT-generated spectra
        std::vector<uint> petiole_obj_ids = plantarchitecture.getPlantPetioleObjectIDs(id);
        std::vector<uint> uuids_petiole = context.getObjectPrimitiveUUIDs(petiole_obj_ids);
        context.setPrimitiveData(uuids_petiole, "reflectivity_spectrum", "leaf_reflectivity_prospect");
        context.setPrimitiveData(uuids_petiole, "transmissivity_spectrum", "leaf_transmissivity_prospect");
        context.setPrimitiveData(uuids_petiole, "specular_exponent", leaf_specular);

        // Update leaf optical properties using PROSPECT-generated spectra
        std::vector<uint> leaf_obj_ids = plantarchitecture.getPlantLeafObjectIDs(id);
        std::vector<uint> uuids_leaf = context.getObjectPrimitiveUUIDs(leaf_obj_ids);
        context.setPrimitiveData(uuids_leaf, "reflectivity_spectrum", "leaf_reflectivity_prospect");
        context.setPrimitiveData(uuids_leaf, "transmissivity_spectrum", "leaf_transmissivity_prospect");
        context.setPrimitiveData(uuids_leaf, "specular_exponent", leaf_specular);
    }
}


void init_spectral_data(Context &context,
                          RadiationModel &radiation,
                          PlantArchitecture &plantarchitecture,
                          LeafOptics& leafoptics,
                          const CameraSetup& camera_setup,
                          json sampled_params) {
    /*
    Inits spectral data. There are three ways to initialize the spectrum data
    1. Load from XML
    2. Blend from radiation model
    3. Using leaf optics model
    */

    auto radiation_cfg = sampled_params["radiationmodel"];
    
    // Part 1: load color and reflectivity data from XML
    std::string colorboard_file = radiation_cfg.value(
        "colorboard", "plugins/radiation/spectral_data/color_board/DGK_DKK_colorboard.xml");
    context.loadXML(colorboard_file.c_str(), true);

#if 0
    // Load leaf surface spectral data with default value
    std::string leaf_spectral_file;
    if (radiation_cfg.contains("leaf_surface_spectral_data") && 
        radiation_cfg["leaf_surface_spectral_data"].contains("file")) {
        leaf_spectral_file = radiation_cfg["leaf_surface_spectral_data"]["file"].get<std::string>();
    } else {
        leaf_spectral_file = "plugins/radiation/spectral_data/leaf_surface_spectral_library.xml";
    }
    context.loadXML(leaf_spectral_file.c_str(), true);
#endif

    // Load soil surface spectral data with default value
    std::string soil_spectral_file;
    if (radiation_cfg.contains("soil_surface_spectral_data") && 
        radiation_cfg["soil_surface_spectral_data"].contains("file")) {
        soil_spectral_file = radiation_cfg["soil_surface_spectral_data"]["file"].get<std::string>();
    } else {
        soil_spectral_file = "plugins/radiation/spectral_data/soil_surface_spectral_library.xml";
    }
    context.loadXML(soil_spectral_file.c_str(), true);
    
    context.renameGlobalData("ColorReference_DGK_08", "spectrum_yellow");
    context.renameGlobalData("ColorReference_DGK_09", "spectrum_green");
    context.renameGlobalData("ColorReference_DGK_16", "spectrum_purple");
    context.renameGlobalData("ColorReference_DGK_01", "spectrum_white");

    // Part 2: blending spectrum  by using radiation model
    // custom flower colors
    radiation.blendSpectra("reflectivity_flower_cowpea_closed",
                           {"spectrum_yellow", "spectrum_green"}, {0.35, 0.65});
    radiation.blendSpectra("reflectivity_flower_cowpea_open",
                           {"spectrum_purple", "spectrum_white"},
                           {0.10, 0.90}); // mostly white with purple tint

    // custom pod colors
    radiation.blendSpectra("reflectivity_pod_cowpea",
                           {"spectrum_yellow", "spectrum_green"}, {0.95, 0.05});

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
    // add the camera to the radiation model
    radiation.addRadiationCamera(cameralabel, bandlabels, camera_setup.camera_position,
                                 camera_setup.camera_lookat, camera_setup.cam_prop, 100);

    // set camera spectral response to simulate iPhone camera
    std::string camera_spectral_file = radiation_cfg["camera_spectral_data"].value(
        "file", "plugins/radiation/spectral_data/camera_spectral_library.xml");
    context.loadXML(camera_spectral_file.c_str(), true);
    std::string camera_type =
        radiation_cfg["camera_spectral_data"]["camera_type"]
            .get<std::string>();
    radiation.setCameraSpectralResponse(cameralabel, "red",
                                        (camera_type + "_red").c_str());
    radiation.setCameraSpectralResponse(cameralabel, "green",
                                        (camera_type + "_green").c_str());
    radiation.setCameraSpectralResponse(cameralabel, "blue",
                                        (camera_type + "_blue").c_str());


    // Part 3: Leaf optics
    // Initialize leaf optics properties with fitted parameters
    LeafOpticsProperties leafopticsprops;
    leafoptics.getPropertiesFromLibrary("prospect", leafopticsprops);
    leafopticsprops.numberlayers = sampled_params["leafoptics"].value("number_layers", 1.5824);
    leafopticsprops.chlorophyllcontent = sampled_params["leafoptics"].value("chlorophyll_content", 37.4129);
    leafopticsprops.carotenoidcontent = sampled_params["leafoptics"].value("carotenoid_content", 12.2658);
    leafopticsprops.anthocyancontent = sampled_params["leafoptics"].value("anthocyan_content", 0.958622);
    leafopticsprops.brownpigments = sampled_params["leafoptics"].value("brown_pigments", 0.01339);
    leafopticsprops.watermass = sampled_params["leafoptics"].value("water_mass", 0.01346);
    leafopticsprops.drymass = sampled_params["leafoptics"].value("dry_mass", 0.00315556);
    leafopticsprops.protein = sampled_params["leafoptics"].value("protein", 0.0);
    leafopticsprops.carbonconstituents = sampled_params["leafoptics"].value("carbon_constituents", 0.0);

    // Run cowpea model to generate leaf_reflectivity_prospect and leaf_transmissivity_prospect
    leafoptics.run(leafopticsprops, "prospect");

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
    bool dry_run = false; // Load and validate JSON without running generation
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
        } else if (arg == "--dry-run") {
            options.dry_run = true;
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
                      << "  --dry-run                Load and validate JSON without running generation\n"
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
        std::cout << "  dry_run: " << (options.dry_run ? "true" : "false") << std::endl;
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
        params_file = "../dap_10_plot_2_12_0000_Method5_+Grounding.json";
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

    // Dry-run mode: validate JSON structure and exit without running generation
    if (args.dry_run) {
        std::cout << "\n" << std::string(60, '=') << std::endl;
        std::cout << "DRY-RUN MODE: Validating JSON structure..." << std::endl;
        std::cout << std::string(60, '=') << std::endl;
        
        // Check required top-level keys
        std::vector<std::string> required_keys = {
            "seed", "field", "sun_position", "plantarchitecture",
            "cameraproperties", "radiationmodel", "leafoptics"
        };
        
        bool all_keys_present = true;
        std::cout << "\nChecking required top-level keys:" << std::endl;
        for (const auto& key : required_keys) {
            bool present = json_params.contains(key);
            std::cout << "  " << key << ": " << (present ? "✓ present" : "✗ MISSING") << std::endl;
            if (!present) all_keys_present = false;
        }
        
        // Check field sub-keys
        std::cout << "\nChecking field parameters:" << std::endl;
        if (json_params.contains("field")) {
            auto& field = json_params["field"];
            std::vector<std::string> field_keys = {"plant_type", "plant_age", "plot_shape", "mode", "plants"};
            for (const auto& key : field_keys) {
                bool present = field.contains(key);
                std::cout << "  field." << key << ": " << (present ? "✓ present" : "✗ MISSING") << std::endl;
                if (!present) all_keys_present = false;
            }
            
            // Check plot_shape sub-keys
            if (field.contains("plot_shape")) {
                auto& plot_shape = field["plot_shape"];
                std::vector<std::string> plot_keys = {"size_x", "size_y", "size_z"};
                for (const auto& key : plot_keys) {
                    bool present = plot_shape.contains(key);
                    std::cout << "  field.plot_shape." << key << ": " << (present ? "✓ present" : "⚠ missing") << std::endl;
                }
            }
            
            // Check plants array
            if (field.contains("plants") && field["plants"].is_array()) {
                int num_plants = field["plants"].size();
                std::cout << "  field.plants: " << num_plants << " plant(s) defined" << std::endl;
                
                // Check first plant structure as sample
                if (num_plants > 0) {
                    auto& first_plant = field["plants"][0];
                    std::vector<std::string> plant_keys = {"bed", "row", "x", "y"};
                    std::cout << "  Sample plant[0] structure:" << std::endl;
                    for (const auto& key : plant_keys) {
                        bool present = first_plant.contains(key);
                        std::cout << "    " << key << ": " << (present ? "✓" : "✗") << std::endl;
                    }
                }
            }
        }
        
        // Check sun_position
        std::cout << "\nChecking sun_position parameters:" << std::endl;
        if (json_params.contains("sun_position")) {
            auto& sun = json_params["sun_position"];
            std::vector<std::string> sun_keys = {"elevation_degrees", "azimuth_degrees"};
            for (const auto& key : sun_keys) {
                bool present = sun.contains(key);
                std::cout << "  sun_position." << key << ": " << (present ? "✓ present" : "✗ MISSING") << std::endl;
            }
        }
        
        // Check cameraproperties
        std::cout << "\nChecking cameraproperties:" << std::endl;
        if (json_params.contains("cameraproperties")) {
            auto& cam = json_params["cameraproperties"];
            std::vector<std::string> cam_keys = {"camera_height", "HFOV", "camera_resolution_x", "camera_resolution_y"};
            for (const auto& key : cam_keys) {
                bool present = cam.contains(key);
                std::cout << "  cameraproperties." << key << ": " << (present ? "✓ present" : "✗ MISSING") << std::endl;
            }
        }
        
        // Check leafoptics (PROSPECT model parameters)
        std::cout << "\nChecking leafoptics (PROSPECT model):" << std::endl;
        if (json_params.contains("leafoptics")) {
            auto& leaf = json_params["leafoptics"];
            std::vector<std::string> leaf_keys = {
                "number_layers", "chlorophyll_content", "carotenoid_content",
                "anthocyan_content", "brown_pigments", "water_mass", "dry_mass"
            };
            for (const auto& key : leaf_keys) {
                bool present = leaf.contains(key);
                std::cout << "  leafoptics." << key << ": " << (present ? "✓ present" : "⚠ missing (will use default)") << std::endl;
            }
        }
        
        // Check plantarchitecture
        std::cout << "\nChecking plantarchitecture:" << std::endl;
        if (json_params.contains("plantarchitecture")) {
            auto& arch = json_params["plantarchitecture"];
            if (arch.contains("phytomer_parameters")) {
                std::cout << "  plantarchitecture.phytomer_parameters: ✓ present" << std::endl;
                if (arch["phytomer_parameters"].contains("leaf_pitch")) {
                    std::cout << "  plantarchitecture.phytomer_parameters.leaf_pitch: ✓ present" << std::endl;
                }
            }
            if (arch.contains("flower_bud_break_probability")) {
                std::cout << "  plantarchitecture.flower_bud_break_probability: ✓ present" << std::endl;
            }
        }
        
        // Summary
        std::cout << "\n" << std::string(60, '=') << std::endl;
        if (all_keys_present) {
            std::cout << "✓ JSON validation PASSED - All required keys present" << std::endl;
        } else {
            std::cout << "✗ JSON validation FAILED - Some required keys are missing" << std::endl;
        }
        std::cout << std::string(60, '=') << std::endl;
        std::cout << "\nDry-run complete. Exiting without running generation." << std::endl;
        
        return all_keys_present ? 0 : 1;
    }

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
    leafoptics.disableMessages();
    RadiationModel radiation(&context);
    PlantArchitecture plantarchitecture(&context);

    for (int i = 0; i < num_iterations; ++i) {
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

        json sampled_params;
        sampled_params = sampleParams(json_params, rng);

        // Save the seed value to sampled_params
        sampled_params["seed"] = final_seed;
        
        // filename with zero-padded iteration number
        std::stringstream filename_stream;
        filename_stream << output_name << "_" << std::setw(4) << std::setfill('0') << i;
        std::string filename = filename_stream.str();


        // Set camera
        CameraSetup camera_setup = init_camera(context, plantarchitecture, sampled_params);
        CameraProperties cam_prop = camera_setup.cam_prop;
        vec3 camera_position = camera_setup.camera_position;
        vec3 camera_lookat = camera_setup.camera_lookat;
        SphericalCoord sun_dir = camera_setup.sun_dir;

        // Init spectra
        if (args.run_radiation) {
            // Initialize the radiation model
            init_spectral_data(context, radiation, plantarchitecture,
                                leafoptics, camera_setup, sampled_params);
        }

        // create ground - either OBJ-based or tile-based
        std::vector<uint> UUIDs_ground;
        
        // Check if use_obj_ground key exists and is not null
        bool use_obj_ground = false;
        try {
            if (sampled_params.contains("field") &&
                sampled_params["field"].contains("plot_shape") &&
                sampled_params["field"]["plot_shape"].contains("use_obj_ground") &&
                !sampled_params["field"]["plot_shape"]["use_obj_ground"].is_null()) {
                use_obj_ground = sampled_params["field"]["plot_shape"]["use_obj_ground"].get<bool>();
                std::cout << "[DEBUG] use_obj_ground = " << use_obj_ground << std::endl;
            } else {
                std::cout << "[DEBUG] field.plot_shape.use_obj_ground key not found or null, using default: false" << std::endl;
            }
        } catch (const std::exception& e) {
            std::cerr << "[ERROR] Failed to read field.plot_shape.use_obj_ground: " << e.what() << std::endl;
            std::cerr << "[ERROR] Using default value: false" << std::endl;
        }
        
        if (use_obj_ground) {
            UUIDs_ground = make_field(context, sampled_params);
        } else {
            // Calculate pixel size on ground based on camera FOV and resolution from params
            auto cam_prop = sampled_params["cameraproperties"];
            float camera_height = cam_prop["camera_height"].get<float>();
            int camera_res_x = cam_prop["camera_resolution_x"].get<int>();
            int camera_res_y = cam_prop["camera_resolution_y"].get<int>();
            
#if 1
            // load dirt texture with fixed size (original method)
            float ground_x = sampled_params["field"]["size_x"].get<float>() * 1.05; // 5 percent buffer
            float ground_y = sampled_params["field"]["size_y"].get<float>() * 1.05; // 5 percent buffer
#else   
            float HFOV = cam_prop["HFOV"].get<float>();
            float HFOV_rad = deg2rad(HFOV);
            // Fix HFOV, and get the VFOV based on image ratio
            float VFOV = HFOVtoVFOV(HFOV, float(camera_res_x) / float(camera_res_y));
            float VFOV_rad = deg2rad(VFOV);
            
            // Ground coverage in each dimension
            float ground_width_visible = 2.0f * camera_height * tan(HFOV_rad / 2.0f);
            float ground_height_visible = 2.0f * camera_height * tan(VFOV_rad / 2.0f);
            // Automatically calculate ground size
            float ground_x = ground_width_visible * 1.05; // 5 percent buffer
            float ground_y = ground_height_visible * 1.05; // 5 percent buffer
#endif
            helios::vec3 tile_center = make_vec3(0, 0, 0);
            helios::vec2 tile_size = make_vec2(0.1, 0.1);
            helios::vec2 field_size = make_vec2(ground_x, ground_y);

            // Pixel size on ground
            float pixel_size_x = ground_x / camera_res_x;
            float pixel_size_y = ground_y / camera_res_y;
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

            if (g_debug_mode) {
                std::cout << "[DEBUG] Ground tile subdivision calculation:" << std::endl;
                std::cout << "  Camera height: " << camera_height << " m" << std::endl;
                std::cout << "  Ground size: " << ground_x << " x " << ground_y << " m" << std::endl;
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
        // Set default color for soil
        context.setPrimitiveData(
            UUIDs_ground, "reflectivity_spectrum",
            sampled_params["radiationmodel"]["soil_surface_spectral_data"]
                        ["reflectivity"]
                            .get<std::string>());
        // Make the ground plane single-sided (only visible from above)
        context.setPrimitiveData(UUIDs_ground, "twosided_flag", 0u);
        // Set ground specular exponent from JSON
        float ground_specular = sampled_params["field"]["plot_shape"].value("specular_exponent", 5.0f);
        context.setPrimitiveData(UUIDs_ground, "specular_exponent", ground_specular);

        // Create multiple plots in a grid pattern
        std::vector<uint> plant_IDs_aging;  // Plants that need aging (built from library, age 0)
        if (mode == GenerationMode::AUTO) {
            // Auto plot generation - Earl
            init_plant_architecture(plantarchitecture, sampled_params);
            auto auto_planting_cfg = sampled_params["field"]["auto_config"];
            // Calculate grid positioning to center all plots
            int num_beds = auto_planting_cfg["num_beds"].get<int>();
            int num_rows = auto_planting_cfg["num_rows"].get<int>();
            float plot_spacing_x =
                auto_planting_cfg["plot_spacing_x"].get<float>();
            float plot_spacing_y =
                auto_planting_cfg["plot_spacing_y"].get<float>();
            float total_size_x = num_beds * plot_spacing_x;
            float total_size_y = num_rows * plot_spacing_y;
            std::cout << "Creating " << num_beds << "x"
                      << num_rows << " plot grid..." << std::endl;

            float start_x = -total_size_x / 2.0f;
            float start_y = -total_size_y / 2.0f;

            // Create plants for this plot
            json plots_array = json::array();
            for (int row = 0; row < num_rows; row++) {
                for (int bed = 0; bed < num_beds; bed++) {
                    // Calculate center position for this plot
                    float plot_x = start_x + bed * plot_spacing_x;
                    float plot_y = start_y + row * plot_spacing_y;

                    std::vector<uint> plot_plant_IDs =
                        plantarchitecture.buildPlantCanopyFromLibrary(
                            make_vec3(plot_x, plot_y, 0),
                            make_vec2(auto_planting_cfg["plant_spacing_x"],
                                      auto_planting_cfg["plant_spacing_y"]),
                            make_int2(auto_planting_cfg["planting_rows"],
                                      auto_planting_cfg["plant_count"]),
                            0);

                    // Add to the aging collection
                    plant_IDs_aging.insert(plant_IDs_aging.end(),
                                         plot_plant_IDs.begin(),
                                         plot_plant_IDs.end());

                    // Add to json
                    json plot_info;
                    plot_info["bed"] = (bed+1);
                    plot_info["row"] = (row+1);
                    
                    json plants_array = json::array();
                    //std::cout << "Num plants in bed " << bed << " row " << row << " => " << plot_plant_IDs.size() << std::endl;
                    //std::cout << "plot_plant_IDs: " << plot_plant_IDs.front() << ".." <<  plot_plant_IDs.back() << std::endl;

                    for (size_t plant_i = 0; plant_i < plot_plant_IDs.size(); plant_i++) {
                        json plant_info;
                        uint plantID = plot_plant_IDs[plant_i];
                        vec3 plant_position = plantarchitecture.getPlantBasePosition(plantID);
                        // Just write absolute position
                        plant_info["x"] = roundToPrecision(plant_position.x, 4);
                        plant_info["y"] = roundToPrecision(plant_position.y, 4);
                        plants_array.push_back(plant_info);
                    }
                    // Update plants
                    plot_info["plants"] = plants_array;
                    plots_array.push_back(plot_info);
                }
            }
            sampled_params["field"]["plots"] = plots_array;

            // Add num_beds and num_rows to sampled_params["field"]
            sampled_params["field"]["num_beds"] = num_beds;
            sampled_params["field"]["num_rows"] = num_rows;
            
            // Update field size and plot size
            sampled_params["field"]["size_x"] = plot_spacing_x * num_beds;
            sampled_params["field"]["size_y"] = plot_spacing_y * num_rows;
            sampled_params["field"]["plot_shape"]["size_x"] = plot_spacing_x;
            sampled_params["field"]["plot_shape"]["size_y"] = plot_spacing_y;


        } else if (mode == GenerationMode::MANUAL) {
            // Manual plot generation - Heesup
            // Support both "size_x"/"width" and "size_y"/"length" field names
            float size_x = 3.0f;  // default
            float size_y = 6.0f; // default

            // Remove auto_config key in manual mode before saving
            if (mode == GenerationMode::MANUAL && sampled_params.contains("field") && 
                sampled_params["field"].contains("auto_config")) {
                sampled_params["field"].erase("auto_config");
            }
            
            try {
                auto& plot_shape = sampled_params["field"]["plot_shape"];
                
                // Try size_x first, then width, else use default
                if (plot_shape.contains("size_x") && !plot_shape["size_x"].is_null()) {
                    size_x = plot_shape["size_x"].get<float>();
                    std::cout << "[DEBUG] Using size_x = " << size_x << std::endl;
                } else if (plot_shape.contains("width") && !plot_shape["width"].is_null()) {
                    size_x = plot_shape["width"].get<float>();
                    std::cout << "[DEBUG] Using width = " << size_x << std::endl;
                } else {
                    std::cout << "[DEBUG] size_x/width not found, using default: " << size_x << std::endl;
                }
                
                // Try size_y first, then length, else use default
                if (plot_shape.contains("size_y") && !plot_shape["size_y"].is_null()) {
                    size_y = plot_shape["size_y"].get<float>();
                    std::cout << "[DEBUG] Using size_y = " << size_y << std::endl;
                } else if (plot_shape.contains("length") && !plot_shape["length"].is_null()) {
                    size_y = plot_shape["length"].get<float>();
                    std::cout << "[DEBUG] Using length = " << size_y << std::endl;
                } else {
                    std::cout << "[DEBUG] size_y/length not found, using default: " << size_y << std::endl;
                }
            } catch (const std::exception& e) {
                std::cerr << "[ERROR] Failed to read size_x/size_y: " << e.what() << std::endl;
                std::cerr << "[ERROR] Using default values: width=" << size_x << ", length=" << size_y << std::endl;
            }
            
            int num_beds = sampled_params["field"]["num_beds"];
            int num_rows = sampled_params["field"]["num_rows"];

            // params.json only have single plant type within plot for now
            // Get crop type and convert to lowercase for plant library
            init_plant_architecture(plantarchitecture, sampled_params);
            auto plots = sampled_params["field"]["plots"];
            int num_plots = plots.size();
            for (int plot_i=0; plot_i < num_plots; plot_i++) {
                int bed = plots[plot_i]["bed"];
                int row = plots[plot_i]["row"];
                auto plants = plots[plot_i]["plants"];
                int num_plants = plants.size();
                for (int plant_j = 0; plant_j < num_plants; plant_j++) {
                    // Select the specific crop
                    json selected_crop = plants[plant_j];
                    
                    // plant count and age can be changed here
                    vec3 origin(0, 0, 0);

                    float X = selected_crop["x"];
                    float Y = selected_crop["y"];
                    origin.x = (bed-1) * size_x;    // plant locations are now absolte, need to be removed?
                    origin.y = (row-1) * size_y; 
                    // float Z = config["crops"][i]["Z"].as<float>();
                    //vec3 plant_origin = origin + make_vec3(X, Y, 0);
                    vec3 plant_origin = make_vec3(X, Y, 0); // Use absolute XY
                    
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
            }
        } else {
            std::cout << "[WARN] plots mode is not defined or invalid!"
                      << std::endl;
            return 0;
        }


        std::vector<uint> UUIDs_plants = plantarchitecture.getAllPlantIDs();
        std::cout << "Number of crops: " << UUIDs_plants.size() << std::endl;
        // Age only plants that were built from library (not from XML)
        if (!plant_IDs_aging.empty()) {
            // plants are planted in a single day -> Age all together
            // Therefore there is no plant_age in plants element
            float plant_age = static_cast<int>(sampled_params["field"]["plant_age"]);
            if (plant_age > 0) {
                //plantarchitecture.advanceTime(plant_IDs_aging, plant_age);
                int days_per_update = 2;
                for(int day = 0; day < plant_age/days_per_update;day++){
                    plantarchitecture.advanceTime(plant_IDs_aging, days_per_update);
                    update_leafoptics(context, plantarchitecture, leafoptics, sampled_params);
                }
                std::cout << "Advanced " << plant_IDs_aging.size() << " plants to age: " << plant_age
                          << " days" << std::endl;
            }
        }
        update_leafoptics(context, plantarchitecture, leafoptics, sampled_params);

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
                int global_plant_i = 0;
                // Assume the plantID will start from plot[0]plant[0]
                auto plots = sampled_params["field"]["plots"];
                int num_plots = plots.size();
                for (int plot_i=0;plot_i < num_plots;plot_i++) {
                    auto plants = plots[plot_i]["plants"];
                    int num_plants = plants.size();
                    std::cout << "num_plants: " << num_plants << std::endl;
                    for (int plant_i = 0; plant_i < num_plants; plant_i++) {
                        sampled_params["field"]["plots"][plot_i]["plants"][plant_i]["xml"] = xml_file_paths[global_plant_i++];
                    }
                }
            }
        }

        // add color calibration target (only when requested)
        // required for RadiationModel::autoCalibrateCameraImage)
        if (args.calibrate_color) {
            CameraCalibration calibration(&context);
            calibration.addCalibriteColorboard(make_vec3(0, 0.75, 0.001), 0.025);
        }

        // save sampled parameters
        std::string params_filename = output_dir + "/" + filename + "_params.json";
        std::ofstream params_file(params_filename);
        // params_file << std::scientific << std::setprecision(4) << sampled_params << std::endl;
        // params_file.close();
        params_file << std::setw(4) << sampled_params << std::endl;
        params_file.close();
        
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
            
            
            // process image using standard pipeline
            // radiation.applyCameraImageCorrections(cameralabel, "red", "green",
            //     "blue", 1.0, 0.5, 1.0);
            printGPUMemoryUsage("After runBand");
            
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