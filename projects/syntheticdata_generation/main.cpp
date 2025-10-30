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


void init_plant_architecture(PlantArchitecture& plantarchitecture,
                             Context& context, json sampled_params) {

    // Load plant from Helios Library
    plantarchitecture.loadPlantModelFromLibrary(sampled_params["plant"]);

    // Get the shoot parameters
    std::map<std::string, ShootParameters> shoot_params =
        plantarchitecture.getCurrentShootParameters();

    // update leaf pitch and peduncle length
    float leaf_pitch =
        sampled_params["plantarchitecture"]["phytomer_parameters"]["leaf_pitch"]
                      ["sampled"];
    float flower_bud_break_prob =
        sampled_params["plantarchitecture"]["flower_bud_break_probability"]
                      ["sampled"];
    shoot_params.at("trifoliate").phytomer_parameters.leaf.pitch = leaf_pitch;
    shoot_params.at("trifoliate").flower_bud_break_probability =
        flower_bud_break_prob;

    // update leaf
    shoot_params.at("trifoliate")
        .phytomer_parameters.leaf.prototype.prototype_function =
        CowpeaLeafPrototype_trifoliate_OBJ;

    // apply updated parameters
    plantarchitecture.updateCurrentShootParameters(
        "trifoliate", shoot_params.at("trifoliate"));

    // enable object data output for flower state identification
    plantarchitecture.optionalOutputObjectData("closedflowerID");
    plantarchitecture.optionalOutputObjectData("openflowerID");

}

void init_camera(json sampled_params, CameraProperties& cameraproperties, 
                vec3& camera_position, vec3& camera_lookat) {
    // camera params
    json cam_prop_json = sampled_params["cameraproperties"];
    
    // focus on center of scene
    cameraproperties.focal_plane_distance =
        cam_prop_json["camera_height"]["sampled"].get<float>() -
        cam_prop_json["focal_plane_distance_difference"]["sampled"].get<float>(); 

    // make it small so it will be in focus
    cameraproperties.lens_diameter =
        cam_prop_json["lens_diameter"]["sampled"].get<float>(); 

    cameraproperties.HFOV = cam_prop_json["HFOV"]["sampled"].get<float>();
    cameraproperties.camera_resolution = make_int2(
        cam_prop_json["camera_resolution_x"]["sampled"].get<int>(),
        cam_prop_json["camera_resolution_y"]["sampled"].get<int>());


    // Calculate plant canopy center based on plant positioning
    vec3 canopy_center = make_vec3(0, 0, 0); // Plants are positioned at origin

    // Convert azimuth angle from degrees to radians
    float azimuth_rad =
        deg2rad(cam_prop_json["camera_positioning"]
                              ["azimuth_angle"]["sampled"]
                                  .get<float>());

    // Calculate camera position based on plant canopy center
    camera_position.x = canopy_center.x +
                        cam_prop_json["camera_positioning"]
                                      ["distance_from_center"]["sampled"]
                                          .get<float>() *
                            cos(azimuth_rad);
    camera_position.y = canopy_center.y +
                        cam_prop_json["camera_positioning"]
                                      ["distance_from_center"]["sampled"]
                                          .get<float>() *
                            sin(azimuth_rad);
    camera_position.z =
        cam_prop_json["camera_height"]["sampled"]
            .get<float>();

    // Calculate camera lookat point (slightly offset from canopy center)
    camera_lookat.x = canopy_center.x + cam_prop_json["camera_positioning"]
                        ["lookat_offset_x"]["sampled"].get<float>();
    camera_lookat.y = canopy_center.y + cam_prop_json["camera_positioning"]
                        ["lookat_offset_y"]["sampled"].get<float>();
    camera_lookat.z = canopy_center.z + cam_prop_json["camera_positioning"]
                        ["lookat_offset_z"]["sampled"].get<float>();
}


void init_radiation_model(Context &context,
                          RadiationModel &radiation,
                          PlantArchitecture &plantarchitecture,
                          LeafOptics& leafoptics,
                          CameraProperties& cameraproperties, 
                          vec3& camera_position, 
                          vec3& camera_lookat,
                          json sampled_params,
                          std::vector<uint> UUIDs_ground,
                          std::vector<uint> UUIDs_plants) {

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

    // prepare custom flower colors
    radiation.blendSpectra("reflectivity_flower_cowpea_closed",
                           {"spectrum_yellow", "spectrum_green"}, {0.35, 0.65});
    radiation.blendSpectra("reflectivity_flower_cowpea_open",
                           {"spectrum_purple", "spectrum_white"},
                           {0.10, 0.90}); // mostly white with purple tint

    DEBUG_PRINT();

    // load color and reflectivity data
    context.loadXML(sampled_params["radiationmodel"]["colorboard"]
                        .get<std::string>().c_str(), true);
    context.loadXML(
        sampled_params["radiationmodel"]["leaf_surface_spectral_data"]["file"]
            .get<std::string>().c_str(), true);
    context.loadXML(
        sampled_params["radiationmodel"]["soil_surface_spectral_data"]["file"]
            .get<std::string>().c_str(), true);
    context.renameGlobalData("ColorReference_DGK_08", "spectrum_yellow");
    context.renameGlobalData("ColorReference_DGK_09", "spectrum_green");
    context.renameGlobalData("ColorReference_DGK_16", "spectrum_purple");
    context.renameGlobalData("ColorReference_DGK_01", "spectrum_white");

    // prepare custom flower colors
    radiation.blendSpectra("reflectivity_flower_cowpea_closed",
                           {"spectrum_yellow", "spectrum_green"}, {0.35, 0.65});
    radiation.blendSpectra("reflectivity_flower_cowpea_open",
                           {"spectrum_purple", "spectrum_white"},
                           {0.10, 0.90}); // mostly white with purple tint

    // assign colors to each object
    context.setPrimitiveData(
        UUIDs_plants, "reflectivity_spectrum",
        sampled_params["radiationmodel"]["leaf_surface_spectral_data"]
                      ["reflectivity"]
                          .get<std::string>());
    context.setPrimitiveData(
        UUIDs_plants, "transmissivity_spectrum",
        sampled_params["radiationmodel"]["leaf_surface_spectral_data"]
                      ["transmissivity"]
                          .get<std::string>());
    context.setPrimitiveData(
        UUIDs_ground, "reflectivity_spectrum",
        sampled_params["radiationmodel"]["soil_surface_spectral_data"]
                      ["reflectivity"]
                          .get<std::string>());

    // set specular properties for realistic shading
    context.setPrimitiveData(UUIDs_plants, "specular_exponent", 10.f);
    context.setPrimitiveData(UUIDs_ground, "specular_exponent", 10.f);

    // get unique labels for flowers and apply colors based on open/closed state
    uint flower_counter = 0;
    uint pod_counter = 0;

    // Initialize leaf optics properties
    LeafOpticsProperties leafopticsprops;
    leafopticsprops.chlorophyllcontent =
        sampled_params["leafoptics"]["chlorophyll_content"]["sampled"]
            .get<int>();

    for (uint &id : UUIDs_plants) {
        std::vector<uint> IDs_flower =
            plantarchitecture.getPlantFlowerObjectIDs(id);
        std::vector<uint> IDs_pod =
            plantarchitecture.getPlantFruitObjectIDs(id);

        for (uint &id_flower : IDs_flower) {
            std::vector<uint> uuids_flower =
                context.getObjectPrimitiveUUIDs(id_flower);

            // check if flower is open or closed based on object data
            bool is_closed_flower = false;
            bool is_open_flower = false;

            if (context.doesObjectDataExist(id_flower, "closedflowerID")) {
                is_closed_flower = true;
            } else if (context.doesObjectDataExist(id_flower, "openflowerID")) {
                is_open_flower = true;
            }

            if (is_closed_flower) {
                context.setPrimitiveData(uuids_flower, "reflectivity_spectrum",
                                         "reflectivity_flower_cowpea_closed");
            } else if (is_open_flower) {
                context.setPrimitiveData(uuids_flower, "reflectivity_spectrum",
                                         "reflectivity_flower_cowpea_open");
            } else {
                context.setPrimitiveData(uuids_flower, "reflectivity_spectrum",
                                         "reflectivity_flower_cowpea_closed");
            }

            context.setPrimitiveData(uuids_flower, "flower", flower_counter);
            flower_counter++;
        }

        // Optional: pod labeling (commented out like in
        // syntheticdata_sample_test) for (uint& id_pod : IDs_pod) {
        //     std::vector<uint> uuids_pod =
        //     context.getObjectPrimitiveUUIDs(id_pod);
        //     context.setPrimitiveData(uuids_pod, "pod", pod_counter);
        //     pod_counter++;
        // }

        // Update leaf optical properties
        std::vector<uint> IDs_leaf =
            plantarchitecture.getPlantLeafObjectIDs(id);
        for (uint &id_leaf : IDs_leaf) {
            std::vector<uint> uuids_leaf =
                context.getObjectPrimitiveUUIDs(id_leaf);
            leafoptics.run(uuids_leaf, leafopticsprops, "cowpea_leaf");
        }
    }

    // set up sun lighting
    SphericalCoord sun_dir = make_SphericalCoord(
        deg2rad(sampled_params["sun_position"]["elevation_degrees"]["sampled"]
                    .get<float>()),
        -deg2rad(sampled_params["sun_position"]["azimuth_degrees"]["sampled"]
                     .get<float>()));
    uint sunID = radiation.addSunSphereRadiationSource(sun_dir);
    radiation.setSourceSpectrum(sunID, "solar_spectrum_direct_ASTMG173");

    // create RGB radiation bands
    radiation.addRadiationBand("red");
    radiation.disableEmission("red");
    radiation.setDiffuseRadiationExtinctionCoeff("red", 0.3f, sun_dir);
    radiation.setScatteringDepth("red", 3);

    radiation.copyRadiationBand("red", "green");
    radiation.copyRadiationBand("red", "blue");

    std::vector<std::string> bandlabels = {"red", "green", "blue"};
    radiation.setDiffuseSpectrum(bandlabels, "solar_spectrum_diffuse_ASTMG173");

    std::string cameralabel = "camera";    

    // add the camera to the radiation model
    radiation.addRadiationCamera(cameralabel, bandlabels, camera_position,
                                 camera_lookat, cameraproperties, 100);

    // set camera spectral response to simulate iPhone camera
    context.loadXML(
        "plugins/radiation/spectral_data/camera_spectral_library.xml", true);
    std::string camera_type =
        sampled_params["radiationmodel"]["camera_spectral_data"]["camera_type"]
            .get<std::string>();
    radiation.setCameraSpectralResponse(cameralabel, "red",
                                        (camera_type + "_red").c_str());
    radiation.setCameraSpectralResponse(cameralabel, "green",
                                        (camera_type + "_green").c_str());
    radiation.setCameraSpectralResponse(cameralabel, "blue",
                                        (camera_type + "_blue").c_str());

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
    bool save_xml = false;
    bool stats_only = false;
    bool gui = false;
    bool run_radiation = true;  // Run faster if running without radiation?
    float height = 1.0f;
    int days = 0;
    unsigned int seed = 0;
    int start_iteration = 0;
    std::string tile_file;
    std::string output_dir;
    std::string plant_model_file;
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
                      << "  -h, --height HEIGHT      Set height value (default: 1.0)\n"
                      << "  -t, --tile FILE          Set tile file path\n"
                      << "  -o, --output DIR         Set output directory (default: from params.json)\n"
                      << "  -f, --file FILE          Set plant model file\n"
                      << "  --days N                 Set number of days (default: 0)\n"
                      << "  -s, --seed N             Set random seed (default: random)\n"
                      << "  -n, --name NAME          Set output name (default: 'plot')\n"
                      << "  -i, --iteration N        Set start iteration (default: 0)\n"
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
            } else if (arg == "-h" || arg == "--height") {
                options.height = std::stof(argv[++i]);
            } else if (arg == "-t" || arg == "--tile") {
                options.tile_file = argv[++i];
            } else if (arg == "-o" || arg == "--output") {
                options.output_dir = argv[++i];
            } else if (arg == "-n" || arg == "--name") {
                options.output_name = argv[++i];
            } else if (arg == "-f" || arg == "--file") {
                options.plant_model_file = argv[++i];
            } else if (arg == "--days") {
                options.days = std::stoi(argv[++i]);
            } else if (arg == "-s" || arg == "--seed") {
                options.seed = static_cast<unsigned int>(std::stoi(argv[++i]));
                std::printf("Seed: %u\n", options.seed);
            } else if (arg == "-i" || arg == "--iteration") {
                options.start_iteration = std::max(std::atoi(argv[++i]), 0);
            } else if (arg == "-p" || arg == "--params") {
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
        std::cout << "  height: " << options.height << std::endl;
        std::cout << "  days: " << options.days << std::endl;
        std::cout << "  seed: " << options.seed << std::endl;
        std::cout << "  start_iteration: " << options.start_iteration << std::endl;
        std::cout << "  tile_file: '" << options.tile_file << "'" << std::endl;
        std::cout << "  output_dir: '" << options.output_dir << "'" << std::endl;
        std::cout << "  plant_model_file: '" << options.plant_model_file << "'" << std::endl;
        std::cout << "  output_name: '" << options.output_name << "'" << std::endl;
        std::cout << "  params_file: '" << options.params_file << "'" << std::endl;
    }

    return options;
}

int main(int argc, char *argv[]) {

    // Parse command-line arguments using dedicated function
    CommandLineOptions args = parseCommandLineArgs(argc, argv);

    // Set up random device and random number generator
    std::random_device rd;
    std::mt19937 rng(args.seed != 0 ? args.seed : rd());

    // load parameters
    std::string params_file;
    if (args.params_file.size() > 0) {
        params_file = args.params_file;
    } else {
        params_file = "../params.json";
    }
    std::cout << "Loading " << params_file << std::endl;
    json json_params = loadParametersFromJson(params_file);

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
    const int num_iterations =
        json_params["iterations"]; // Change this to desired number of images

    if (args.start_iteration >= num_iterations) {
        std::cout << "Starting iteration (" << args.start_iteration
                  << ") is >= total iterations (" << num_iterations
                  << "). Nothing to do." << std::endl;
        return 0;
    }
    if (args.start_iteration > 0) {
        std::cout << "Resuming from iteration " << args.start_iteration << std::endl;
    }

    auto plots = json_params["plots"];
    // Parse generation mode
    GenerationMode mode = GenerationMode::UNKNOWN;
    if (plots.contains("mode") && plots["mode"].is_string()) {
        mode = parseGenerationMode(plots["mode"].get<std::string>());
    }

    // Declare context
    Context context;
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

        // Recursively add "sampled" values to all parameters
        sampled_params = sampleParams(json_params, rng);

        // save sampled parameters
        std::ofstream params_file(output_dir + "/" + filename + "_params.json");
        params_file << std::setw(4) << sampled_params << std::endl;
        params_file.close();

        // Create multiple plots in a grid pattern
        std::vector<uint> all_plant_IDs;
        auto plot_cfg = sampled_params["plots"];
        auto pa_init = sampled_params["plantarchitecture"]["initialize"];
        if (mode == GenerationMode::AUTO) {
            // Auto plot generation - Earl
            init_plant_architecture(plantarchitecture, context, sampled_params);

            // Calculate grid positioning to center all plots
            int num_beds = plot_cfg["num_beds"]["sampled"].get<int>();
            int num_rows = plot_cfg["num_rows"]["sampled"].get<int>();
            float bed_spacing_x =
                plot_cfg["bed_spacing_x"]["sampled"].get<float>();
            float bed_spacing_y =
                plot_cfg["bed_spacing_y"]["sampled"].get<float>();
            float total_bed_width = (num_beds - 1) * bed_spacing_x;
            float total_bed_height = (num_rows - 1) * bed_spacing_y;
            float start_x = -total_bed_width / 2.0f;
            float start_y = -total_bed_height / 2.0f;

            std::cout << "Creating " << num_beds << "x"
                      << num_rows << " plot grid..." << std::endl;

            // Create plants for this plot
            for (int row = 0; row < num_rows; ++row) {
                for (int bed = 0; bed < num_beds; ++bed) {
                    // Calculate position for this plot
                    float plot_x = start_x + bed * bed_spacing_x;
                    float plot_y = start_y + row * bed_spacing_y;

                    std::vector<uint> plot_plant_IDs =
                        plantarchitecture.buildPlantCanopyFromLibrary(
                            make_vec3(plot_x, plot_y, 0),
                            make_vec2(pa_init["plant_spacing_x"]["sampled"],
                                      pa_init["plant_spacing_y"]["sampled"]),
                            make_int2(pa_init["num_columns"]["sampled"],
                                      pa_init["plant_count"]["sampled"]),
                            0);

                    // Add to the total collection
                    all_plant_IDs.insert(all_plant_IDs.end(),
                                         plot_plant_IDs.begin(),
                                         plot_plant_IDs.end());
                }
            }
            std::cout << "done " << std::endl;
        } else if (mode == GenerationMode::MANUAL) {
            // Manual plot generation - Heesup
            int num_crops = 0;
            if (plot_cfg.contains("crops") && plot_cfg["crops"].is_array()) {
                num_crops = plot_cfg["crops"].size();
            }
            std::cout << "Number of crops: " << num_crops << std::endl;

            for (int j = 0; j < num_crops; j++) {
                // Select the specific crop
                json selected_crop = sampled_params["plots"]["crops"][j];

                // Get crop type and convert to lowercase for plant library
                std::string crop_type = selected_crop["crop_type"].get<std::string>();
                
                // override plant type
                sampled_params["plant"] = crop_type;
                init_plant_architecture(plantarchitecture, context, sampled_params);
                
                // plant count and age can be changed here
                vec3 origin(0, 0, 0);
                int bed = selected_crop["bed"];
                int row = selected_crop["row"];
                float X = selected_crop["x"];
                float Y = selected_crop["y"];
                // float Z = config["crops"][i]["Z"].as<float>();
                vec3 plant_origin = origin + make_vec3(X, Y, 0);
                uint plantID = plantarchitecture.buildPlantInstanceFromLibrary(
                    plant_origin, 0);
                all_plant_IDs.push_back(plantID);
                std::cout << "Generated plant (ID:" << plantID << ")"
                          << std::endl;
            }
        } else {
            std::cout << "[WARN] plots mode is not defined or invalid!"
                      << std::endl;
            return 0;
        }

        // create ground - either OBJ-based or tile-based
        std::vector<uint> UUIDs_ground;
        if (sampled_params["ground"]["use_obj_ground"].get<bool>()) {
            UUIDs_ground = createObjGround(context, sampled_params);
            DEBUG_PRINT("OBJ ground created");
        } else {
            // load dirt texture with fixed size (original method)
            float ground_x = sampled_params["ground"]["size_x"]["sampled"];
            float ground_y = sampled_params["ground"]["size_y"]["sampled"];
            helios::vec3 tile_center = make_vec3(0, 0, 0);
            helios::vec2 tile_size = make_vec2(1, 1);
            helios::vec2 field_size = make_vec2(ground_x, ground_y);
            int2 texture_repeat = make_int2(ground_x / tile_size.x, ground_y / tile_size.y);
            // std::vector<uint> Context::addTile(const vec3 &center, const vec2
            // &size, const SphericalCoord &rotation, const int2 &subdiv, const
            // char *texturefile, const int2 &texture_repeat) {
            UUIDs_ground = context.addTile(tile_center, field_size,
                                           make_SphericalCoord(0, 0),
                                           make_int2(3000, 3000), // Subdivision
                                           "plugins/visualizer/textures/dirt.jpg",
                                           texture_repeat);
        }

        std::vector<uint> UUIDs_plants = plantarchitecture.getAllPlantIDs();
        // Age all plants together after creation
        if (!UUIDs_plants.empty()) {
            float plant_age = static_cast<int>(pa_init["plant_age"]["sampled"]);
            if (plant_age > 0) {
                plantarchitecture.advanceTime(UUIDs_plants, plant_age);
                std::cout << "Advanced all plants to age: " << plant_age
                          << " days" << std::endl;
            }
        }

        
        // Write the plant structure to an XML file
        if (args.save_xml) {
            for (int i = 0; i < UUIDs_plants.size(); i++) {
                uint plantID = UUIDs_plants[i];
                // filename with zero-padded plant number
                std::stringstream filename_stream;
                filename_stream << filename << "_plant_" << std::setw(4)
                << std::setfill('0') << i << ".xml";
                std::string xml_file_name = output_dir + "/" + filename_stream.str();
                plantarchitecture.writePlantStructureXML(plantID, xml_file_name);
            }
        }

        // add color calibration target 
        // required for RadiationModel::autoCalibrateCameraImage)
        CameraCalibration calibration(&context);
        calibration.addCalibriteColorboard(make_vec3(0, 0.75, 0.001), 0.025);

        // Set camera
        CameraProperties cam_prop;
        vec3 camera_position(0, 0, 0);
        vec3 camera_lookat(0, 0, 0);
        init_camera(sampled_params, cam_prop, camera_position, camera_lookat);

        // By default, run visualizer
        Visualizer vis(cam_prop.camera_resolution.x, cam_prop.camera_resolution.y);
        if (args.debug) {
            // Add a reference object
            vec3 position(1, 1, 0.1);       //(x,y,z) position of patch center
            vec2 size(1, 1);                // length and width of patch
            SphericalCoord coord(1, 0, 0);  // r=1, el=0, az=0, 
            context.addPatch(position, size, coord, "../img_1x1.png");
        }
        vis.clearGeometry();
        vis.buildContextGeometry(&context);
        vis.hideWatermark();
        vis.disableMessages();


        // set up sun lighting
        SphericalCoord sun_dir = make_SphericalCoord(
            deg2rad(
                sampled_params["sun_position"]["elevation_degrees"]["sampled"]
                    .get<float>()),
            -deg2rad(
                sampled_params["sun_position"]["azimuth_degrees"]["sampled"]
                    .get<float>()));

        // Convert SphericalCoord to direction vector
        vec3 sun_direction = sphere2cart(sun_dir);
        vis.setLightDirection(sun_direction);
        vis.setLightingModel(Visualizer::LIGHTING_PHONG_SHADOWED);
        //vis.setLightingModel(Visualizer::LIGHTING_PHONG); // No shadow
        vis.setCameraPosition(camera_position, camera_lookat); 
        vis.setCameraFieldOfView(cam_prop.HFOV);
        vis.plotUpdate(true);
        // Save the image to the file.
        std::string save_path = output_dir + "/" + filename + "_vis.jpeg";
        vis.printWindow(save_path.c_str());

        if (args.gui) {
            // plotInteractive for GUI mode
            vis.plotInteractive();
        }

        // #if 0
        //     // Generate annotations
        //     // Declare the Synthetic Annotation class.
        //     SyntheticAnnotation annotation(&context);
        //     //annotation.setCameraPosition(field_origin +
        //     make_vec3(0, 0, 10), field_origin);
        //     //annotation.setCameraPosition(make_vec3(0, 0, 1),
        //     make_vec3(1, 0, 1));
        //     annotation.setCameraPosition(make_vec3(0, 0, 5),
        //     make_vec3(1, 0, 0)); // 왜 이렇게 해야하는지 잘 모르겠음
        //     annotation.disableInstanceSegmentation();
        //     //annotation.setWindowSize(800, 800);

        //     // Add labels according to whatever scheme we want.
        //     for (int p = 0; p < canopygenerator.getPlantCount(); p++)
        //     {
        //         // loop over plants
        //         //if (!config.simulation_type.empty() &&
        //         config.simulation_type[0] == "rgb")
        //         {
        // annotation.labelPrimitives(canopygenerator.getTrunkUUIDs(p),
        //             "trunks");
        // annotation.labelPrimitives(canopygenerator.getBranchUUIDs(p),
        //             "branches");
        // annotation.labelPrimitives(canopygenerator.getLeafUUIDs(p),
        //             "leaves");
        //             std::vector<std::vector<std::vector<uint>>>
        //             fruitUUIDs = canopygenerator.getFruitUUIDs(p); if
        //             (fruitUUIDs.size() == 1) { // no clusters, only
        //             individual fruit
        //                 for (auto &fruit : fruitUUIDs.front())
        //                     annotation.labelPrimitives(fruit,
        //                     "clusters");
        //             }
        //             else if (fruitUUIDs.size() > 1)
        //             { // fruit contained within cluster - label by
        //             cluster
        //                 for (auto &cluster : fruitUUIDs)
        //                     annotation.labelPrimitives(flatten(cluster),
        //                     "clusters");
        //             }
        //         }
        //     }
        //     // Render the annotations.
        //     std::string this_image_dir =
        //     std::string("rendered_images/annotations"); std::cout <<
        //     this_image_dir;
        //     annotation.render(this_image_dir.c_str());
        // #endif

        //     return 0;
        // }

        // Run radiation model by default true
        if (args.run_radiation) {
            // Initialize the radiation model
            init_radiation_model(context, radiation, plantarchitecture,
                                 leafoptics, cam_prop, camera_position,
                                 camera_lookat, sampled_params, UUIDs_ground,
                                 UUIDs_plants);

            std::vector<std::string> bandlabels = {"red", "green", "blue"};
            std::string cameralabel = "camera";

            // update geometry and run radiation model
            radiation.updateGeometry();

            radiation.runBand(bandlabels);

            // process image using standard pipeline
            radiation.applyImageProcessingPipeline(cameralabel, "red", "green",
                                                   "blue");

            // save rendered RGB image with custom filename
            std::string image_file = radiation.writeCameraImage(
                cameralabel, bandlabels, "RGB", output_dir, 0);
            std::string image_base = fs::path(image_file).stem().string();

            // export bounding boxes and segmentation masks in COCO format
            radiation.writeImageSegmentationMasks(
                cameralabel, {"flower"}, {0},
                output_dir + '/' + filename + "_labels.json", image_file);

            // auto-calibrate camera using colorboard reference values with
            // quality report
            std::string corrected_image = radiation.autoCalibrateCameraImage(
                cameralabel, "red", "green", "blue",
                output_dir + '/' + filename + ".jpeg", true);

            // Delete the uncalibrated image after calibrated version is created
            try {
                if (fs::exists(image_file)) {
                    fs::remove(image_file);
                }
            } catch (const std::exception &e) {
                std::cout << "  Warning: Could not delete uncalibrated image "
                          << image_file << ": " << e.what() << std::endl;
            }
        }
    }

    std::cout << "\nCompleted all " << num_iterations
              << " iterations. Parameters saved to individual JSON files."
              << std::endl;

     return 0;
}