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
#include "EnergyBalanceModel.h"
#include "BoundaryLayerConductanceModel.h"
#include "StomatalConductanceModel.h"
#include "PhotosynthesisModel.h"

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

template <typename T>
T getJsonNumberOr(const json& root,
                 std::initializer_list<const char*> keys,
                 T default_value);

bool getJsonBoolOr(const json& root,
                  std::initializer_list<const char*> keys,
                  bool default_value);

std::string getJsonStringOr(const json& root,
                           std::initializer_list<const char*> keys,
                           const std::string& default_value);

void init_plant_architecture(PlantArchitecture& plantarchitecture,
                             json sampled_params) {

    // Load plant from Helios Library
    plantarchitecture.loadPlantModelFromLibrary(getJsonStringOr(sampled_params, {"metadata", "plant_type"}, "cowpea"));

    plantarchitecture.disableMessages();
    // Get the shoot parameters
    std::map<std::string, ShootParameters> shoot_params =
        plantarchitecture.getCurrentShootParameters();

    // update leaf pitch and peduncle length
    const float leaf_pitch = getJsonNumberOr<float>(
        sampled_params,
        {"plant_properties", "architecture", "phytomer_parameters", "leaf_pitch"},
        0.0f);
    const float flower_bud_break_probability = getJsonNumberOr<float>(
        sampled_params,
        {"plant_properties", "architecture", "flower_bud_break_probability"},
        0.4f);

    shoot_params.at("trifoliate").phytomer_parameters.leaf.pitch = leaf_pitch;
    shoot_params.at("trifoliate").flower_bud_break_probability =
        flower_bud_break_probability;


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

CameraSetup init_camera(Context& context, PlantArchitecture &plantarchitecture, json& sampled_params) {
    CameraSetup setup;
    
    // camera params
    json cam_prop_json = sampled_params["camera"];
    
    // focus on center of scene
    const float camera_height_default = 5.0f;
    const float focal_plane_distance_difference_default = 0.5f;
    const float camera_height = getJsonNumberOr<float>(
        cam_prop_json, {"positioning", "camera_height"}, camera_height_default);
    const float focal_plane_distance_difference = getJsonNumberOr<float>(
        cam_prop_json,
        {"sensor", "focal_plane_distance_difference"},
        focal_plane_distance_difference_default);
    setup.cam_prop.focal_plane_distance =
        camera_height - focal_plane_distance_difference;

    // make it small so it will be in focus
    setup.cam_prop.lens_diameter =
        getJsonNumberOr<float>(cam_prop_json, {"sensor", "lens_diameter"}, 0.0028f);
    // Clamp lens_diameter to prevent ISO mode from producing f_number = infinity → zero exposure.
    // HELIOS ISO exposure uses: gain = ISO * shutter / f_number², where f_number = focal_length / lens_diameter.
    // A pinhole (lens_diameter=0) makes f_number infinite → gain=0 → pitch-black image.
    if (setup.cam_prop.lens_diameter < 1e-4f) {
        setup.cam_prop.lens_diameter = 0.0028f; // default ~f/46 aperture
    }

    float single_plot_x = getJsonNumberOr<float>(
        sampled_params, {"field", "layout", "plot_size_x"}, 1.299f);
    float single_plot_y = getJsonNumberOr<float>(
        sampled_params, {"field", "layout", "plot_size_y"}, 3.831f);
    int num_beds = getJsonNumberOr<int>(sampled_params, {"field", "num_beds"}, 1);
    int num_rows = getJsonNumberOr<int>(sampled_params, {"field", "num_rows"}, 1);
    
    float ground_x = single_plot_x * num_beds;
    
    // Changes HFOV to exactly cover horizontal field width without margin.
    // Vertical coverage is handled natively by matching image resolution aspect ratio.
    setup.cam_prop.HFOV = calculateFOV(ground_x, camera_height);
    setup.cam_prop.camera_resolution = make_int2(
        getJsonNumberOr<int>(cam_prop_json, {"sensor", "resolution_x"}, 720),
        getJsonNumberOr<int>(cam_prop_json, {"sensor", "resolution_y"}, 720));
    
    // Read exposure settings from JSON
    // Exposure mode: "auto" (automatic exposure), "ISO" (ISO-based), or "manual" (no automatic exposure scaling)
    std::string exposure_mode = getJsonStringOr(
        cam_prop_json, {"sensor", "exposure_mode"}, "ISO");
    int iso_value = getJsonNumberOr<int>(cam_prop_json, {"sensor", "ISO"}, 100);
    std::string shutter_speed_str = getJsonStringOr(
        cam_prop_json, {"sensor", "shutter_speed"}, "1/125");
        
    // Calculate Dynamic ISO if mode is "ISO" (dynamically scaled by sun elevation to fix dark dirt)
    if (exposure_mode == "ISO") {
        float sun_elevation_rad = deg2rad(getJsonNumberOr<float>(
            sampled_params, {"environment", "sun", "elevation_degrees"}, 45.0f));
        float sin_el = std::max(0.1f, std::sin(sun_elevation_rad));
        
        // Calculate f-number to compensate for tiny aperture (f/43.2 vs f/2.8 reference)
        float lens_focal_length = getJsonNumberOr<float>(cam_prop_json, {"sensor", "focal_length"}, 129.63f);
        float lens_diameter_mm = setup.cam_prop.lens_diameter * 1000.0f; // lens_diameter is in meters
        float f_number = lens_focal_length / std::max(lens_diameter_mm, 0.001f);
        float ref_f_number = 2.8f;
        float aperture_compensation = (f_number / ref_f_number) * (f_number / ref_f_number);
        
        // Prevent double-compensation of ISO when re-loading an output params.json
        // that already contains a dynamically-computed ISO value.
        // Template ISO is typically 100; after one init_camera() pass it becomes ~6k–68k.
        float base_iso;
        if (iso_value > 1000) {
            std::cout << "[WARN] ISO value " << iso_value
                      << " appears pre-computed. Resetting base_iso to 100 to avoid double-compensation."
                      << std::endl;
            base_iso = 100.0f;
        } else {
            base_iso = iso_value > 0 ? (float)iso_value : 100.0f;
        }
        float exposure_scale = 0.25f; // Scale down exposure by 2 stops (few steps lower) to prevent too bright images
        iso_value = static_cast<int>((base_iso * aperture_compensation * exposure_scale) / sin_el);
        
        // Write the updated ISO value back to JSON so it gets saved
        sampled_params["camera"]["sensor"]["ISO"] = iso_value;
    }
    
    if (exposure_mode == "auto") {
        setup.cam_prop.exposure = "auto";
    } else if (exposure_mode == "ISO" || iso_value > 0) {
        // Set ISO-based exposure (e.g., "ISO100", "ISO12800")
        setup.cam_prop.exposure = "ISO" + std::to_string(iso_value);
        
        // Parse shutter speed from "1/125" format or decimal
        if (shutter_speed_str.find('/') != std::string::npos) {
            size_t slash_pos = shutter_speed_str.find('/');
            float numerator = std::stof(shutter_speed_str.substr(0, slash_pos));
            float denominator = std::stof(shutter_speed_str.substr(slash_pos + 1));
            setup.cam_prop.shutter_speed = numerator / denominator;
        } else {
            setup.cam_prop.shutter_speed = std::stof(shutter_speed_str);
        }
    } else {
        setup.cam_prop.exposure = "manual";
    }

    // Calculate exact geometric midpoint of all plot origins as the default canopy center
    // Each plot origin is (bed-1)*plot_size_x and (row-1)*plot_size_y.
    // The exact midpoint across the grid is thus (num_beds-1)*plot_size_x*0.5f and (num_rows-1)*plot_size_y*0.5f.
    single_plot_y = getJsonNumberOr<float>(
        sampled_params, {"field", "layout", "plot_size_y"}, 3.831f);
    num_rows = getJsonNumberOr<int>(sampled_params, {"field", "num_rows"}, 1);
    vec3 canopy_center = make_vec3(single_plot_x * (num_beds - 1) * 0.5f, single_plot_y * (num_rows - 1) * 0.5f, 0.0f);
    
    // Check if focusing_plants key exists and is not null
    bool focusing_plants = getJsonBoolOr(
        cam_prop_json, {"positioning", "focusing_plants"}, false);
    std::cout << "[DEBUG] focusing_plants = " << focusing_plants << std::endl;
    
    if (focusing_plants) {
        std::cout << "[DEBUG] focusing_plants is true, calculating bounding box..." << std::endl;
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

    std::cout << "[DEBUG] Calculating azimuth..." << std::endl;
    std::cout << "[DEBUG] Getting azimuth from JSON..." << std::endl;
    float azimuth_deg = getJsonNumberOr<float>(
        cam_prop_json, {"positioning", "azimuth_angle"}, 0.0f);
    std::cout << "[DEBUG] azimuth_deg = " << azimuth_deg << std::endl;
    
    std::cout << "[DEBUG] Converting to radians..." << std::endl;
    float azimuth_rad = deg2rad(azimuth_deg);
    std::cout << "[DEBUG] azimuth_rad = " << azimuth_rad << std::endl;

    std::cout << "[DEBUG] Calculating camera distance..." << std::endl;
    float dist = getJsonNumberOr<float>(
        cam_prop_json, {"positioning", "distance_from_center"}, 0.01f);
    std::cout << "[DEBUG] dist = " << dist << std::endl;

    std::cout << "[DEBUG] Setting camera_position.x..." << std::endl;
    setup.camera_position.x = canopy_center.x + dist*sin(azimuth_rad); 
    std::cout << "[DEBUG] Setting camera_position.y..." << std::endl;
    setup.camera_position.y = canopy_center.y - dist*cos(azimuth_rad);
    std::cout << "[DEBUG] Setting camera_position.z..." << std::endl;
    setup.camera_position.z = camera_height;

    std::cout << "[DEBUG] Setting camera_lookat..." << std::endl;
    // Calculate camera lookat point (slightly offset from canopy center)
    setup.camera_lookat.x = canopy_center.x + getJsonNumberOr<float>(
        cam_prop_json, {"positioning", "lookat_offset_x"}, 0.0f);
    setup.camera_lookat.y = canopy_center.y + getJsonNumberOr<float>(
        cam_prop_json, {"positioning", "lookat_offset_y"}, 0.0f);
    setup.camera_lookat.z = canopy_center.z + getJsonNumberOr<float>(
        cam_prop_json, {"positioning", "lookat_offset_z"}, 0.0f);

    setup.sun_dir = make_SphericalCoord(
        deg2rad(getJsonNumberOr<float>(
            sampled_params, {"environment", "sun", "elevation_degrees"}, 45.0f)),
        deg2rad(getJsonNumberOr<float>(
            sampled_params, {"environment", "sun", "azimuth_degrees"}, 180.0f)));
    std::cout << "[DEBUG] init_camera complete. Returning setup." << std::endl;
    return setup;
}

void update_leafoptics(Context &context,
                        PlantArchitecture &plantarchitecture,
                        LeafOptics& leafoptics,
                        json sampled_params) {
    
    // Extract leaf specular exponent from JSON with default value
    float leaf_specular = sampled_params["plant_properties"]["leaf_optics"].value("specular_exponent", 2.0f);
    
    // Get plantarchitecture plant ids
    std::vector<uint> plant_ids = plantarchitecture.getAllPlantIDs();

    // Set default color for the plant
    std::vector<uint> UUIDs_plants = plantarchitecture.getAllUUIDs();
    context.setPrimitiveData(
        UUIDs_plants, "reflectivity_spectrum","leaf_reflectivity_prospect");
    context.setPrimitiveData(
        UUIDs_plants, "transmissivity_spectrum","leaf_transmissivity_prospect");

    for (uint &id : plant_ids) {
        // label plants (skip if already labeled with unique global IDs)
        // std::vector<uint> single_plant_UUIDs = plantarchitecture.getAllPlantObjectIDs(id);
        // std::vector<uint> uuids_plant = context.getObjectPrimitiveUUIDs(single_plant_UUIDs);
        // context.setPrimitiveData(uuids_plant, "plant", id);
        
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
                          const std::string& cameralabel,
                          RadiationModel &radiation,
                          PlantArchitecture &plantarchitecture,
                          LeafOptics& leafoptics,
                          const CameraSetup& camera_setup,
                          const json& sampled_params,
                          bool run_multispectral,
                          bool run_temperature,
                          bool run_wue) {
    /*
    Inits spectral data. There are three ways to initialize the spectrum data
    1. Load from XML
    2. Blend from radiation model
    3. Using leaf optics model
    */
    std::cout << "[DEBUG] init_spectral_data started..." << std::endl;

    // Note: spectral data configuration is now under environment.soil
    std::cout << "[DEBUG] Accessing soil_cfg..." << std::endl;
    auto soil_cfg = sampled_params["environment"]["soil"];
    std::cout << "[DEBUG] soil_cfg accessed." << std::endl;
    auto radiation_cfg = json::object(); // Placeholder for backward compatibility
    
    // Part 1: load color and reflectivity data from XML
    std::string colorboard_file = radiation_cfg.value(
        "colorboard", "plugins/radiation/spectral_data/color_board/DGK_DKK_colorboard.xml");
    std::cout << "[DEBUG] Loading colorboard XML..." << std::endl;
    context.loadXML(colorboard_file.c_str(), true);
    std::cout << "[DEBUG] colorboard XML loaded." << std::endl;

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
    if (soil_cfg.contains("spectral_data") && 
        soil_cfg["spectral_data"].contains("file")) {
        soil_spectral_file = soil_cfg["spectral_data"]["file"].get<std::string>();
    } else {
        soil_spectral_file = "plugins/radiation/spectral_data/soil_surface_spectral_library.xml";
    }
    std::cout << "[DEBUG] Loading soil spectral XML..." << std::endl;
    context.loadXML(soil_spectral_file.c_str(), true);
    std::cout << "[DEBUG] soil spectral XML loaded." << std::endl;
    
    std::cout << "[DEBUG] Renaming global data..." << std::endl;
    context.renameGlobalData("ColorReference_DGK_08", "spectrum_yellow");
    context.renameGlobalData("ColorReference_DGK_09", "spectrum_green");
    context.renameGlobalData("ColorReference_DGK_16", "spectrum_purple");
    context.renameGlobalData("ColorReference_DGK_01", "spectrum_white");

    std::cout << "[DEBUG] Blending spectra..." << std::endl;
    // Part 2: blending spectrum  by using radiation model
    std::cout << "[DEBUG] Blending reflectivity_flower_cowpea_closed..." << std::endl;
    radiation.blendSpectra("reflectivity_flower_cowpea_closed",
                           {"spectrum_yellow", "spectrum_green"}, {0.35, 0.65});
    std::cout << "[DEBUG] Blending reflectivity_flower_cowpea_open..." << std::endl;
    radiation.blendSpectra("reflectivity_flower_cowpea_open",
                           {"spectrum_purple", "spectrum_white"},
                           {0.10, 0.90}); // mostly white with purple tint

    std::cout << "[DEBUG] Blending reflectivity_pod_cowpea..." << std::endl;
    // custom pod colors
    radiation.blendSpectra("reflectivity_pod_cowpea",
                           {"spectrum_yellow", "spectrum_green"}, {0.95, 0.05});

    // set up sun lighting
    std::cout << "[DEBUG] Adding sun sphere radiation source..." << std::endl;
    std::cout << "[DEBUG] sun_dir: elevation=" << camera_setup.sun_dir.elevation << ", azimuth=" << camera_setup.sun_dir.azimuth << std::endl;
    uint sunID = radiation.addSunSphereRadiationSource(camera_setup.sun_dir);
    std::cout << "[DEBUG] sunID = " << sunID << std::endl;
    std::cout << "[DEBUG] Setting source spectrum..." << std::endl;
    radiation.setSourceSpectrum(sunID, "solar_spectrum_direct_ASTMG173");
    std::cout << "[DEBUG] Source spectrum set." << std::endl;

    std::cout << "[DEBUG] Adding radiation bands..." << std::endl;
    // create RGB radiation bands
    radiation.addRadiationBand("red");
    radiation.disableEmission("red");
    radiation.setDiffuseRadiationExtinctionCoeff("red", 0.3f, camera_setup.sun_dir);
    radiation.setScatteringDepth("red", 3);

    radiation.copyRadiationBand("red", "green");
    radiation.copyRadiationBand("red", "blue");
    if (run_multispectral) {
        radiation.copyRadiationBand("red", "NIR");
    }
    if (run_temperature) {
        radiation.copyRadiationBand("red", "LW");
        radiation.setScatteringDepth("LW", 1);
    }
    if (run_wue) {
        radiation.addRadiationBand("wue_band");
    }

    std::vector<std::string> bandlabels = {"red", "green", "blue"};
    if (run_multispectral) {
        bandlabels.push_back("NIR");
    }
    if (run_temperature) {
        bandlabels.push_back("LW");
    }
    if (run_wue) {
        bandlabels.push_back("wue_band");
    }
    radiation.setDiffuseSpectrum("solar_spectrum_diffuse_ASTMG173");
   
    std::cout << "[DEBUG] Adding radiation camera: " << cameralabel << std::endl;
    // add the camera to the radiation model
    radiation.addRadiationCamera(cameralabel.c_str(), bandlabels, camera_setup.camera_position,
                                 camera_setup.camera_lookat, camera_setup.cam_prop, 100);
    std::cout << "[DEBUG] Radiation camera added." << std::endl;

    std::cout << "[DEBUG] Loading camera spectral library..." << std::endl;
    // set camera spectral response to simulate iPhone camera
    auto camera_cfg = sampled_params["camera"]["sensor"];
    std::string camera_spectral_library = "plugins/radiation/spectral_data/camera_spectral_library.xml";
    context.loadXML(camera_spectral_library.c_str(), true);
    
    std::string camera_model = getJsonStringOr(camera_cfg, {"model"}, "Basler_acA2500-20gc");
    std::cout << "[DEBUG] camera_model = " << camera_model << std::endl;

    std::cout << "[DEBUG] Setting camera spectral responses..." << std::endl;
    radiation.setCameraSpectralResponse(cameralabel.c_str(), "red",
                                        (camera_model + "_red").c_str());
    radiation.setCameraSpectralResponse(cameralabel.c_str(), "green",
                                        (camera_model + "_green").c_str());
    radiation.setCameraSpectralResponse(cameralabel.c_str(), "blue",
                                        (camera_model + "_blue").c_str());


    // Part 3: Leaf optics
    // Initialize leaf optics properties with fitted parameters
    LeafOpticsProperties leafopticsprops;
    leafoptics.getPropertiesFromLibrary("prospect", leafopticsprops);
    auto leaf_opt = sampled_params["plant_properties"]["leaf_optics"];
    leafopticsprops.numberlayers = leaf_opt.value("number_layers", 1.5824);
    leafopticsprops.chlorophyllcontent = leaf_opt.value("chlorophyll_content", 37.4129);
    leafopticsprops.carotenoidcontent = leaf_opt.value("carotenoid_content", 12.2658);
    leafopticsprops.anthocyancontent = leaf_opt.value("anthocyan_content", 0.958622);
    leafopticsprops.brownpigments = leaf_opt.value("brown_pigments", 0.01339);
    leafopticsprops.watermass = leaf_opt.value("water_mass", 0.01346);
    leafopticsprops.drymass = leaf_opt.value("dry_mass", 0.00315556);
    leafopticsprops.protein = leaf_opt.value("protein", 0.0);
    leafopticsprops.carbonconstituents = leaf_opt.value("carbon_constituents", 0.0);

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
        } else if (arg == "--stats-only") {
            options.stats_only = true;
        } else if (arg == "--save-xml") {
            options.save_xml = true;
        } else if (arg == "--no-save-xml") {
            options.save_xml = false;
        } else if (arg == "--gui") {
            options.gui = true;
        } else if (arg == "--focus-plant") {
            // Boolean flag that can optionally be followed by true/false to override JSON
            if (i + 1 < argc) {
                std::string focus_flag = argv[i + 1];
                if (focus_flag == "false" || focus_flag == "0") {
                    options.focus_plant = 0;
                    ++i;
                } else if (focus_flag == "true" || focus_flag == "1") {
                    options.focus_plant = 1;
                    ++i;
                } else {
                    options.focus_plant = 1; // no value: just enable
                }
            } else {
                options.focus_plant = 1;
            }
        } else if (arg == "--dry-run") {
            options.dry_run = true;
        } else if (arg == "--help") {
            // Print help message
            std::cout << "Usage: " << argv[0] << " [OPTIONS]\n"
                      << "Options:\n"
                      << "  --renderer MODE          Output renderer: vis, radiation, all (default), or none\n"
                      << "  --save-xml               Save plant structure XML files (default: true)\n"
                      << "  --no-save-xml            Skip saving XML files\n"
                      << "  -r, --rotation           Enable rotation view\n"
                      << "  -g, --grow               Enable grow mode\n"
                      << "  -d, --debug              Enable debug mode\n"
                      << "  --stats-only             Only output statistics\n"
                      << "  --gui                    Enable GUI interactive mode\n"
                       << "  --calibrate-color true|false  Add color calibration panel and auto-calibrate output image (default: false)\n"
                       << "  --dry-run                Load and validate JSON without running generation\n"
                       << "  -h, --height HEIGHT      Override camera height in meters (default: from params.json)\n"
                       << "  --fov DEGREES            Override horizontal FOV in degrees (default: auto-calculated from field size)\n"
                       << "  --focus-plant [true|false] Auto-fit FOV to plant bounding box + 5% margin (overrides --fov and JSON focusing_plants)\n"
                       << "  -t, --tile FILE          Set tile file path\n"
                      << "  -o, --output DIR         Set output directory (default: from params.json)\n"
                      << "  -f, --file FILE          Set plant param file\n"
                      << "  --dap N, --days N        Override DAP (days-after-planting) from JSON metadata (e.g. --dap 10)\n"
                      << "  -s, --seed N             Set random seed (default: random)\n"
                      << "  -n, --name NAME          Set output name (default: 'plot')\n"
                      << "  -i, --iteration N        Set iterations (default: 0)\n"
                      << "  --help                   Show this help message\n";
            std::exit(0);
        }
        // Options with arguments
        else if (i + 1 < argc) {
            if (arg == "--renderer") {
                std::string renderer_flag = argv[++i];
                if (renderer_flag == "none") {
                    options.renderer = Renderer::NONE;
                } else if (renderer_flag == "vis") {
                    options.renderer = Renderer::VIS;
                } else if (renderer_flag == "radiation") {
                    options.renderer = Renderer::RADIATION;
                } else if (renderer_flag == "all") {
                    options.renderer = Renderer::ALL;
                } else {
                    std::printf("Invalid value for --renderer: %s (use vis/radiation/all/none)\n", renderer_flag.c_str());
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
            } else if (arg == "--multispectral") {
                std::string ms_flag = argv[++i];
                if (ms_flag == "false" || ms_flag == "0") options.run_multispectral = false;
                else if (ms_flag == "true" || ms_flag == "1") options.run_multispectral = true;
            } else if (arg == "--temperature" || arg == "--thermal") {
                std::string temp_flag = argv[++i];
                if (temp_flag == "false" || temp_flag == "0") options.run_temperature = false;
                else if (temp_flag == "true" || temp_flag == "1") options.run_temperature = true;
            } else if (arg == "--depth") {
                std::string depth_flag = argv[++i];
                if (depth_flag == "false" || depth_flag == "0") options.run_depth = false;
                else if (depth_flag == "true" || depth_flag == "1") options.run_depth = true;
            } else if (arg == "--wue" || arg == "--run_wue") {
                std::string wue_flag = argv[++i];
                if (wue_flag == "false" || wue_flag == "0") options.run_wue = false;
                else if (wue_flag == "true" || wue_flag == "1") options.run_wue = true;
            } else if (arg == "-h" || arg == "--height") {
                options.height = std::stof(argv[++i]);
            } else if (arg == "-t" || arg == "--tile") {
                options.tile_file = argv[++i];
            } else if (arg == "-o" || arg == "--output") {
                options.output_dir = argv[++i];
            } else if (arg == "-n" || arg == "--name") {
                options.output_name = argv[++i];
            } else if (arg == "--days" || arg == "--dap") {
                options.dap = std::stoi(argv[++i]);
            } else if (arg == "--fov") {
                options.fov = std::stof(argv[++i]);
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
        std::cout << "  renderer: " << static_cast<int>(options.renderer) << " (0=none,1=vis,2=radiation,3=all)" << std::endl;
        std::cout << "  calibrate_color: " << (options.calibrate_color ? "true" : "false") << std::endl;
        std::cout << "  dry_run: " << (options.dry_run ? "true" : "false") << std::endl;
        std::cout << "  height: " << options.height << std::endl;
        std::cout << "  dap: " << options.dap << std::endl;
        std::cout << "  seed: " << options.seed << std::endl;
        std::cout << "  num_iterations: " << options.num_iterations << std::endl;
        std::cout << "  tile_file: '" << options.tile_file << "'" << std::endl;
        std::cout << "  output_dir: '" << options.output_dir << "'" << std::endl;
        std::cout << "  output_name: '" << options.output_name << "'" << std::endl;
        std::cout << "  params_file: '" << options.params_file << "'" << std::endl;
    }

    return options;
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

    if (g_debug_mode) {
        // Save the original parameters once (shared across all crops)
        std::ofstream original_params_file(output_dir + "/original_params.json");
        original_params_file << std::setw(4) << json_params << std::endl;
        original_params_file.close();
        std::cout << "Saved original parameters to: original_params.json"
        << std::endl;
    }

    // Dry-run mode: validate JSON structure and exit without running generation
    if (args.dry_run) {
        std::cout << "\n" << std::string(60, '=') << std::endl;
        std::cout << "DRY-RUN MODE: Validating JSON structure..." << std::endl;
        std::cout << std::string(60, '=') << std::endl;
        
        // Check required top-level keys
        std::vector<std::string> required_keys = {
            "seed", "metadata", "environment", "field",
            "plant_properties", "camera"
        };
        
        bool all_keys_present = true;
        std::cout << "\nChecking required top-level keys:" << std::endl;
        for (const auto& key : required_keys) {
            bool present = json_params.contains(key);
            std::cout << "  " << key << ": " << (present ? "✓ present" : "✗ MISSING") << std::endl;
            if (!present) all_keys_present = false;
        }
        
        // Check metadata sub-keys
        std::cout << "\nChecking metadata parameters:" << std::endl;
        if (json_params.contains("metadata")) {
            auto& metadata = json_params["metadata"];
            std::vector<std::string> metadata_keys = {"plant_type", "dap", "year", "location"};
            for (const auto& key : metadata_keys) {
                bool present = metadata.contains(key);
                std::cout << "  metadata." << key << ": " << (present ? "✓ present" : "✗ MISSING") << std::endl;
                if (key == "plant_type" || key == "dap") {
                    if (!present) all_keys_present = false;
                }
            }
        }
        
        // Check field sub-keys
        std::cout << "\nChecking field parameters:" << std::endl;
        if (json_params.contains("field")) {
            auto& field = json_params["field"];
            std::vector<std::string> field_keys = {"layout", "plots"};
            for (const auto& key : field_keys) {
                bool present = field.contains(key);
                std::cout << "  field." << key << ": " << (present ? "✓ present" : "✗ MISSING") << std::endl;
                if (!present) all_keys_present = false;
            }
            
            // Check layout sub-keys
            if (field.contains("layout")) {
                auto& layout = field["layout"];
                std::cout << "  field.layout.mode: " << (layout.contains("mode") ? "✓ present" : "⚠ missing") << std::endl;
                if (layout.contains("sampling")) {
                    auto& sampling = layout["sampling"];
                    std::vector<std::string> sampling_keys = {"plot_size_x", "plot_size_y", "plot_size_z"};
                    for (const auto& key : sampling_keys) {
                        bool present = sampling.contains(key);
                        std::cout << "  field.layout.sampling." << key << ": " << (present ? "✓ present" : "⚠ missing") << std::endl;
                    }
                }
            }
            
            // Check plots array
            if (field.contains("plots") && field["plots"].is_array()) {
                int num_plots = field["plots"].size();
                std::cout << "  field.plots: " << num_plots << " plot(s) defined" << std::endl;
                
                // Check first plot structure as sample
                if (num_plots > 0) {
                    auto& first_plot = field["plots"][0];
                    std::cout << "  Sample plots[0] structure:" << std::endl;
                    std::cout << "    bed: " << (first_plot.contains("bed") ? "✓" : "✗") << std::endl;
                    std::cout << "    row: " << (first_plot.contains("row") ? "✓" : "✗") << std::endl;
                    if (first_plot.contains("plants") && first_plot["plants"].is_array() && first_plot["plants"].size() > 0) {
                        auto& first_plant = first_plot["plants"][0];
                        std::cout << "    plants[0].x: " << (first_plant.contains("x") ? "✓" : "✗") << std::endl;
                        std::cout << "    plants[0].y: " << (first_plant.contains("y") ? "✓" : "✗") << std::endl;
                    }
                }
            }
        }
        
        // Check environment
        std::cout << "\nChecking environment parameters:" << std::endl;
        if (json_params.contains("environment")) {
            auto& env = json_params["environment"];
            std::cout << "  environment.sun: " << (env.contains("sun") ? "✓ present" : "✗ MISSING") << std::endl;
            std::cout << "  environment.soil: " << (env.contains("soil") ? "✓ present" : "✗ MISSING") << std::endl;
            
            if (env.contains("sun")) {
                auto& sun = env["sun"];
                std::vector<std::string> sun_keys = {"elevation_degrees", "azimuth_degrees", "shadow"};
                for (const auto& key : sun_keys) {
                    bool present = sun.contains(key);
                    std::cout << "  environment.sun." << key << ": " << (present ? "✓ present" : "✗ MISSING") << std::endl;
                }
            }
            
            if (env.contains("soil")) {
                auto& soil = env["soil"];
                std::cout << "  environment.soil.spectral_data: " << (soil.contains("spectral_data") ? "✓ present" : "⚠ missing") << std::endl;
            }
        }
        
        // Check camera
        std::cout << "\nChecking camera parameters:" << std::endl;
        if (json_params.contains("camera")) {
            auto& cam = json_params["camera"];
            std::cout << "  camera.sensor: " << (cam.contains("sensor") ? "✓ present" : "✗ MISSING") << std::endl;
            std::cout << "  camera.positioning: " << (cam.contains("positioning") ? "✓ present" : "✗ MISSING") << std::endl;
            
            if (cam.contains("sensor")) {
                auto& sensor = cam["sensor"];
                std::vector<std::string> sensor_keys = {"resolution_x", "resolution_y", "focal_plane_distance_difference", "lens_diameter"};
                for (const auto& key : sensor_keys) {
                    bool present = sensor.contains(key);
                    std::cout << "  camera.sensor." << key << ": " << (present ? "✓ present" : "⚠ missing") << std::endl;
                }
            }
            
            if (cam.contains("positioning")) {
                auto& pos = cam["positioning"];
                std::vector<std::string> pos_keys = {"camera_height", "azimuth_angle", "distance_from_center"};
                for (const auto& key : pos_keys) {
                    bool present = pos.contains(key);
                    std::cout << "  camera.positioning." << key << ": " << (present ? "✓ present" : "⚠ missing") << std::endl;
                }
            }
        }
        
        // Check plant_properties (PROSPECT model parameters)
        std::cout << "\nChecking plant_properties:" << std::endl;
        if (json_params.contains("plant_properties")) {
            auto& plant_props = json_params["plant_properties"];
            std::cout << "  plant_properties.leaf_optics: " << (plant_props.contains("leaf_optics") ? "✓ present" : "✗ MISSING") << std::endl;
            std::cout << "  plant_properties.architecture: " << (plant_props.contains("architecture") ? "✓ present" : "✗ MISSING") << std::endl;
            
            if (plant_props.contains("leaf_optics")) {
                auto& leaf = plant_props["leaf_optics"];
                std::vector<std::string> leaf_keys = {
                    "number_layers", "chlorophyll_content", "carotenoid_content",
                    "anthocyan_content", "brown_pigments", "water_mass", "dry_mass"
                };
                for (const auto& key : leaf_keys) {
                    bool present = leaf.contains(key);
                    std::cout << "  plant_properties.leaf_optics." << key << ": " << (present ? "✓ present" : "⚠ missing (will use default)") << std::endl;
                }
            }
            
            if (plant_props.contains("architecture")) {
                auto& arch = plant_props["architecture"];
                if (arch.contains("phytomer_parameters")) {
                    std::cout << "  plant_properties.architecture.phytomer_parameters: ✓ present" << std::endl;
                    auto& phyto = arch["phytomer_parameters"];
                    if (phyto.contains("leaf_pitch")) {
                        std::cout << "  plant_properties.architecture.phytomer_parameters.leaf_pitch: ✓ present" << std::endl;
                    }
                }
                if (arch.contains("flower_bud_break_probability")) {
                    std::cout << "  plant_properties.architecture.flower_bud_break_probability: ✓ present" << std::endl;
                }
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
    if (field.contains("layout") && field["layout"].contains("mode") && field["layout"]["mode"].is_string()) {
        mode = parseGenerationMode(field["layout"]["mode"].get<std::string>());
    }


    for (int i = 0; i < num_iterations; ++i) {
        json sampled_params;
        sampled_params = sampleParams(json_params, rng);

        // Save the seed value to sampled_params
        sampled_params["seed"] = final_seed;
        
        std::cout << "[DEBUG] Creating fresh context and models for iteration " << i << "..." << std::endl;
        Context context;
        context.seedRandomGenerator(final_seed);
        
        LeafOptics leafoptics(&context);
        leafoptics.disableMessages();
        const bool run_radiation = (args.renderer == Renderer::RADIATION || args.renderer == Renderer::ALL);
        const bool run_vis = (args.renderer == Renderer::VIS || args.renderer == Renderer::ALL);

        std::unique_ptr<RadiationModel> radiation_ptr;
        if (run_radiation) {
            try {
                radiation_ptr = std::make_unique<RadiationModel>(&context);
            } catch (const std::exception &e) {
                std::cerr << "Warning: GPU RadiationModel unavailable. Disabling radiation: " << e.what() << std::endl;
                args.renderer = Renderer::NONE;
            }
        }
        PlantArchitecture plantarchitecture(&context);
        std::cout << "[DEBUG] Context and models initialized." << std::endl;
        
        // filename with zero-padded iteration number
        std::stringstream filename_stream;
        filename_stream << output_name << "_" << std::setw(4) << std::setfill('0') << i;
        std::string filename = filename_stream.str();


        // Allow --height command-line argument to override camera_height in JSON
        if (args.height > 0.0f) {
            sampled_params["camera"]["positioning"]["camera_height"] = args.height;
            std::cout << "[INFO] Camera height overridden by --height flag: " << args.height << " m" << std::endl;
        }

        // Set camera
        //std::string cameralabel = "camera";
        std::string cameralabel = "camera";
        CameraSetup camera_setup = init_camera(context, plantarchitecture, sampled_params);

        // Allow --fov command-line argument to override the auto-calculated HFOV
        if (args.fov > 0.0f) {
            camera_setup.cam_prop.HFOV = args.fov;
            std::cout << "[INFO] HFOV overridden by --fov flag: " << args.fov << " degrees" << std::endl;
        }
        vec3 camera_position = camera_setup.camera_position;
        vec3 camera_lookat = camera_setup.camera_lookat;
        SphericalCoord sun_dir = camera_setup.sun_dir;

        // Set up ground
        std::vector<uint> UUIDs_ground;
        
        std::cout << "[DEBUG] sampled_params before use_obj_ground check: " << sampled_params.dump() << std::endl;

        bool use_obj_ground = getJsonBoolOr(
            sampled_params, {"environment", "soil", "use_obj_ground"}, true);
        if (use_obj_ground) {
            // Compatibility shim for make_field in field.cpp
            // field.cpp expects num_beds, num_rows in field/ and plot_shape in field/
            if (sampled_params.contains("field")) {
                auto& field = sampled_params["field"];
                if (field.contains("layout")) {
                    json layout = field["layout"]; // Use copy to avoid dangling ref when field is mutated
                    if (!field.contains("num_beds") && layout.contains("num_beds")) {
                        field["num_beds"] = layout["num_beds"];
                    }
                    if (!field.contains("num_rows") && layout.contains("num_rows")) {
                        field["num_rows"] = layout["num_rows"];
                    }
                    if (!field.contains("plot_shape")) {
                        field["plot_shape"] = layout;
                    }
                    // Also ensure obj_file_path is available where make_field expects it
                    std::cout << "[DEBUG] Checking for plot_shape and obj_file_path..." << std::endl;
                    if (field.is_object() && field.contains("plot_shape") && field["plot_shape"].is_object()) {
                        if (!field["plot_shape"].contains("obj_file_path")) {
                            if (sampled_params.contains("environment") && 
                                sampled_params["environment"].contains("soil") &&
                                sampled_params["environment"]["soil"].contains("obj_file_path")) {
                                std::cout << "[DEBUG] Copying obj_file_path to plot_shape..." << std::endl;
                                field["plot_shape"]["obj_file_path"] = sampled_params["environment"]["soil"]["obj_file_path"];
                            }
                        }
                    }
                }
            }
            std::cout << "[DEBUG] Calling make_field with sampled_params..." << std::endl;
            UUIDs_ground = make_field(context, sampled_params);
            std::cout << "[DEBUG] make_field returned " << UUIDs_ground.size() << " primitives." << std::endl;
        } else {
            // Calculate pixel size on ground based on camera FOV and resolution from params
            auto cam_config = sampled_params["camera"];
            float camera_height = getJsonNumberOr<float>(
                cam_config, {"positioning", "camera_height"}, 5.0f);
            int camera_res_x = getJsonNumberOr<int>(
                cam_config, {"sensor", "resolution_x"}, 720);
            int camera_res_y = getJsonNumberOr<int>(
                cam_config, {"sensor", "resolution_y"}, 720);
            
            // load dirt texture with fixed size (original method)
            // Therefore the camera height will be the dominant paramter that makes the camera perelex effect
            float ground_x = getJsonNumberOr<float>(
                sampled_params, {"field", "layout", "plot_size_x"}, 1.299f) * 1.05f; // 5 percent buffer
            float ground_y = getJsonNumberOr<float>(
                sampled_params, {"field", "layout", "plot_size_y"}, 3.831f) * 1.05f; // 5 percent buffer
            //float ground_x = sampled_params["field"]["layout"]["plot_size_x"].get<float>() * 2; // 200 percent buffer
            //float ground_y = sampled_params["field"]["layout"]["plot_size_y"].get<float>() * 2; // 200 percent buffer

            helios::vec3 tile_center = make_vec3(0, 0, 0);
            helios::vec2 tile_size = make_vec2(0.1, 0.1);
            helios::vec2 field_size = make_vec2(ground_x, ground_y);

            // Pixel size on ground
            float pixel_plot_size_x = ground_x / camera_res_x;
            float pixel_plot_size_y = ground_y / camera_res_y;
            float pixel_size = std::max(pixel_plot_size_x, pixel_plot_size_y);
            
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
            // ROOT CAUSE: addTile stores texture UV in patch's vertex data but does NOT set
            // material.texture_file. Visualizer::buildContextGeometry reads getPrimitiveTextureFile()
            // which returns material.texture_file — so it gets an empty string and renders solid black.
            // addPatch WITH a texture path DOES set material.texture_file correctly → works in Visualizer.
            //
            // SOLUTION: Use both:
            //   1. addPatch("dirt.jpg") → Visualizer texture rendering
            //   2. addTile (no texture, subdivided) → radiation model fine-grained shadow computation
            // Both at z=0 so they overlap. addTile primitives are invisible to Visualizer (no texture_file)
            // but provide radiation absorption surface with high spatial resolution.

            // (1) Single textured patch for Visualizer
            uint patch_uuid = context.addPatch(
                tile_center,
                field_size,
                make_SphericalCoord(0.f, 0.f),
                "plugins/visualizer/textures/dirt.jpg"
            );
            UUIDs_ground.push_back(patch_uuid);

            // (2) Fine-subdivided tile for radiation model shadow resolution
            int2 tile_subdiv = make_int2(clamped_subdiv_x, clamped_subdiv_y);
            std::vector<uint> UUIDs_radiation_tile = context.addTile(
                make_vec3(0, 0, -0.0001f), // slightly below so no z-fighting with visual patch
                field_size,
                make_SphericalCoord(0, 0),
                tile_subdiv
            );
            UUIDs_ground.insert(UUIDs_ground.end(), UUIDs_radiation_tile.begin(), UUIDs_radiation_tile.end());
        }
        if (use_obj_ground) {
            // Set default color and specular for soil when using 3D obj ground
            context.setPrimitiveData(
                UUIDs_ground, "reflectivity_spectrum",
                getJsonStringOr(
                    sampled_params,
                    {"environment", "soil", "spectral_data", "reflectivity"},
                    "soil_reflectivity_0003"));
            float ground_specular = sampled_params["environment"]["soil"].value("specular_exponent", 5.0f);
            context.setPrimitiveData(UUIDs_ground, "specular_exponent", ground_specular);
        }
        // Make the ground plane double-sided so it is visible from all camera angles
        context.setPrimitiveData(UUIDs_ground, "twosided_flag", 1u);
        
        // Add explicit Longwave (LW) band radiative properties for soil ground
        context.setPrimitiveData(UUIDs_ground, "reflectivity_LW", 0.05f);
        context.setPrimitiveData(UUIDs_ground, "emissivity_LW", 0.95f);

        // Create multiple plots in a grid pattern
        std::vector<uint> plant_IDs_aging;  // Plants that need aging (built from library, age 0)
        if (mode == GenerationMode::AUTO) {
            // Auto plot generation - Earl
            // In auto mode, use auto config to geneate plots and remove the config
            // If double row plant thing in auto mode, it will double the nuber of plants?
            init_plant_architecture(plantarchitecture, sampled_params);
            auto auto_planting_cfg = sampled_params["field"]["layout"]["sampling"];
            // Calculate grid positioning to center all plots
            int num_beds = auto_planting_cfg["num_beds"].get<int>();
            int num_rows = auto_planting_cfg["num_rows"].get<int>();
            float plot_size_x =
                auto_planting_cfg["plot_size_x"].get<float>();
            float plot_size_y =
                auto_planting_cfg["plot_size_y"].get<float>();
            float total_plot_size_x = num_beds * plot_size_x;
            float total_plot_size_y = num_rows * plot_size_y;
            std::cout << "Creating " << num_beds << "x"
                      << num_rows << " plot grid..." << std::endl;

            float start_x = -total_plot_size_x / 2.0f;
            float start_y = -total_plot_size_y / 2.0f;

            // Create plants for this plot
            json plots_array = json::array();
            for (int row = 0; row < num_rows; row++) {
                for (int bed = 0; bed < num_beds; bed++) {
                    // Calculate center position for this plot
                    float plot_x = start_x + bed * plot_size_x;
                    float plot_y = start_y + row * plot_size_y;

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
            sampled_params["field"]["plot_size_x"] = plot_size_x;
            sampled_params["field"]["plot_size_y"] = plot_size_y;
            
        } else if (mode == GenerationMode::MANUAL) {
            // Manual plot generation - Heesup
            // In manual mode, use the predefined plots 
            // Support both "plot_size_x"/"width" and "plot_size_y"/"length" field names
            float plot_size_x = 3.0f;  // default
            float plot_size_y = 6.0f; // default

            // Remove auto_sampling key in manual mode before saving
            if (mode == GenerationMode::MANUAL && sampled_params.contains("field") && 
                sampled_params["field"].contains("layout") && 
                sampled_params["field"]["layout"].contains("sampling")) {
                // auto_sampling will be deleted when python geneates it
                sampled_params["field"]["layout"].erase("sampling");
            }
            auto& plot_shape = sampled_params["field"]["layout"];
            plot_size_x = getJsonNumberOr<float>(plot_shape, {"plot_size_x"}, 1.299f);
            plot_size_y = getJsonNumberOr<float>(plot_shape, {"plot_size_y"}, 3.831f);
            int num_beds = getJsonNumberOr<int>(plot_shape, {"num_beds"}, 1);
            int num_rows = getJsonNumberOr<int>(plot_shape, {"num_rows"}, 1);

            // params.json only have single plant type within plot for now
            // Get crop type and convert to lowercase for plant library
            init_plant_architecture(plantarchitecture, sampled_params);
            auto plots = sampled_params["field"]["plots"];
            int num_plots = plots.size();
            uint global_plant_id = 0;
            uint global_flower_id = 0;
            uint global_pod_id = 0;
            for (int plot_i=0; plot_i < num_plots; plot_i++) {
                int bed = plots[plot_i].value("bed", 1);
                int row = plots[plot_i].value("row", 1);

                auto plants = plots[plot_i]["plants"];
                int num_plants = plants.size();
                for (int plant_j = 0; plant_j < num_plants; plant_j++) {
                    // Select the specific crop
                    json selected_crop = plants[plant_j];
                    
                    // plant count and age can be changed here
                    vec3 origin(0, 0, 0);

                    float X = selected_crop.value("x", 0.0f);
                    float Y = selected_crop.value("y", 0.0f);

                    origin.x = (bed-1) * plot_size_x;
                    origin.y = (row-1) * plot_size_y; 
                    
                    // Add bed and row offset to plant origin
                    vec3 plant_origin = origin + make_vec3(X, Y, 0);
                    
                    // Check if xml path is provided and valid
                    if (selected_crop.contains("xml") && 
                        selected_crop["xml"].is_string() && 
                        !selected_crop["xml"].get<std::string>().empty()) {
                        // Build plant from XML file
                        std::string xml_path = selected_crop["xml"].get<std::string>();
                        std::vector<uint> plot_plant_IDs;
                        plot_plant_IDs = plantarchitecture.readPlantStructureXML(xml_path, 0);
                        
                        // Translate XML loaded plant coordinates by the plot offset
                        for(int i=0; i < plot_plant_IDs.size(); i++) {
                            uint pid = plot_plant_IDs[i];
                            vec3 shift = make_vec3(origin.x, origin.y, 0);
                            
                            // 1. Update logical plant base position
                            plantarchitecture.setPlantBasePosition(pid, shift);
                            
                            // 2. Force translate all 3D mesh objects associated with this plant
                            std::vector<uint> single_plant_obj_ids = plantarchitecture.getAllPlantObjectIDs(pid);
                            for (uint obj_id : single_plant_obj_ids) {
                                context.translateObject(obj_id, shift);
                            }
                            
                            std::cout << "Loaded plant from XML (ID:" << pid << ") and forcefully translated by (" << origin.x << ", " << origin.y << "): " << xml_path << std::endl;
                            
                            // Label XML plant primitives with unique global ID
                            std::vector<uint> uuids_xml_plant = context.getObjectPrimitiveUUIDs(plantarchitecture.getAllPlantObjectIDs(pid));
                            context.setPrimitiveData(uuids_xml_plant, "plant", global_plant_id++);
                            
                            // Label flowers/pods for XML plants as well
                            std::vector<uint> flower_objs = plantarchitecture.getPlantFlowerObjectIDs(pid);
                            for (uint f_obj : flower_objs) {
                                std::vector<uint> uuids_f = context.getObjectPrimitiveUUIDs(f_obj);
                                context.setPrimitiveData(uuids_f, "flower", global_flower_id++);
                            }
                            std::vector<uint> pod_objs = plantarchitecture.getPlantFruitObjectIDs(pid);
                            for (uint p_obj : pod_objs) {
                                std::vector<uint> uuids_p = context.getObjectPrimitiveUUIDs(p_obj);
                                context.setPrimitiveData(uuids_p, "pod", global_pod_id++);
                            }
                        }
                    } else {
                        // Build plant from library (needs aging)
                        uint plantID;
                        plantID = plantarchitecture.buildPlantInstanceFromLibrary(plant_origin, true);
                        plant_IDs_aging.push_back(plantID);
                        std::cout << "Generated plant from library (ID:" << plantID << ")" << std::endl;
                    }

                    // Assign unique global IDs for Bounding Box and Segmentation consistency
                    uint current_plant_id = 0;
                    if (selected_crop.contains("xml")) {
                        // XML loading can return multiple plants, but we usually treat as one or handle IDs
                        // For now, use the first ID returned or handle carefully
                    } else {
                        current_plant_id = plant_IDs_aging.back();
                        
                        // Label plant primitives with unique global ID
                        std::vector<uint> uuids_plant = context.getObjectPrimitiveUUIDs(plantarchitecture.getAllPlantObjectIDs(current_plant_id));
                        context.setPrimitiveData(uuids_plant, "plant", global_plant_id++);
                        
                        // Label flowers with unique global IDs
                        std::vector<uint> flower_objs = plantarchitecture.getPlantFlowerObjectIDs(current_plant_id);
                        for (uint f_obj : flower_objs) {
                            std::vector<uint> uuids_f = context.getObjectPrimitiveUUIDs(f_obj);
                            context.setPrimitiveData(uuids_f, "flower", global_flower_id++);
                        }
                        
                        // Label pods with unique global IDs
                        std::vector<uint> pod_objs = plantarchitecture.getPlantFruitObjectIDs(current_plant_id);
                        for (uint p_obj : pod_objs) {
                            std::vector<uint> uuids_p = context.getObjectPrimitiveUUIDs(p_obj);
                            context.setPrimitiveData(uuids_p, "pod", global_pod_id++);
                        }
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
            // Therefore there is no dap in plants element
            // Allow --dap command-line argument to override the JSON metadata value
            if (args.dap >= 0) {
                sampled_params["metadata"]["dap"] = args.dap;
                std::cout << "[INFO] DAP overridden by --dap flag: " << args.dap << " days" << std::endl;
            }
            float dap = getJsonNumberOr<float>(sampled_params, {"metadata", "dap"}, 0.0f);
            if (dap > 0) {
                plantarchitecture.advanceTime(plant_IDs_aging, dap);
                update_leafoptics(context, plantarchitecture, leafoptics, sampled_params);
                std::cout << "Advanced " << plant_IDs_aging.size() << " plants to age: " << dap
                          << " days" << std::endl;
            }
        }
        update_leafoptics(context, plantarchitecture, leafoptics, sampled_params);

        // Re-assign unique global primitive instance IDs for "plant", "flower", and "pod" AFTER aging/growth completes!
        uint final_plant_id = 0;
        uint final_flower_id = 0;
        uint final_pod_id = 0;

        for (uint plantID : UUIDs_plants) {
            std::vector<uint> uuids_plant = context.getObjectPrimitiveUUIDs(plantarchitecture.getAllPlantObjectIDs(plantID));
            if (!uuids_plant.empty()) {
                context.setPrimitiveData(uuids_plant, "plant", final_plant_id++);
            }

            std::vector<uint> flower_objs = plantarchitecture.getPlantFlowerObjectIDs(plantID);
            for (uint f_obj : flower_objs) {
                std::vector<uint> uuids_f = context.getObjectPrimitiveUUIDs(f_obj);
                if (!uuids_f.empty()) {
                    context.setPrimitiveData(uuids_f, "flower", final_flower_id++);
                }
            }

            std::vector<uint> pod_objs = plantarchitecture.getPlantFruitObjectIDs(plantID);
            for (uint p_obj : pod_objs) {
                std::vector<uint> uuids_p = context.getObjectPrimitiveUUIDs(p_obj);
                if (!uuids_p.empty()) {
                    context.setPrimitiveData(uuids_p, "pod", final_pod_id++);
                }
            }
        }
        std::cout << "[INFO] Re-labeled primitive instance IDs after aging: " << final_plant_id << " plants, " << final_flower_id << " flowers, " << final_pod_id << " pods." << std::endl;

        // Determine whether to apply plant-focused FOV. CLI flag overrides JSON.
        bool json_focus_plants = getJsonBoolOr(
            sampled_params, {"camera", "positioning", "focusing_plants"}, false);
        bool effective_focus_plant = (args.focus_plant == 1) ||
                                     (args.focus_plant == -1 && json_focus_plants);

        // Plant-focused FOV: recalculate HFOV to fit all plant primitives' XY bounding box + 5% margin
        if (effective_focus_plant) {
            float bb_min_x = std::numeric_limits<float>::max();
            float bb_min_y = std::numeric_limits<float>::max();
            float bb_max_x = std::numeric_limits<float>::lowest();
            float bb_max_y = std::numeric_limits<float>::lowest();

            for (uint plantID : UUIDs_plants) {
                std::vector<uint> plant_uuids = plantarchitecture.getAllPlantUUIDs(plantID);
                for (uint uuid : plant_uuids) {
                    std::vector<helios::vec3> verts = context.getPrimitiveVertices(uuid);
                    for (const auto& v : verts) {
                        bb_min_x = std::min(bb_min_x, v.x);
                        bb_min_y = std::min(bb_min_y, v.y);
                        bb_max_x = std::max(bb_max_x, v.x);
                        bb_max_y = std::max(bb_max_y, v.y);
                    }
                }
            }

            if (bb_max_x > bb_min_x && bb_max_y > bb_min_y) {
                float span_x = (bb_max_x - bb_min_x) * 1.05f; // +5% margin
                float span_y = (bb_max_y - bb_min_y) * 1.05f;
                float max_span = std::max(span_x, span_y);
                float cam_h = camera_setup.camera_position.z;
                float new_hfov = calculateFOV(max_span, cam_h);
                std::cout << "[INFO] focus-plant: plant XY span = " << span_x << " x " << span_y
                          << " m, camera_height = " << cam_h
                          << " m, new HFOV = " << new_hfov << " deg" << std::endl;
                camera_setup.cam_prop.HFOV = new_hfov;
            } else {
                std::cout << "[WARN] focus-plant: could not compute plant bounding box, keeping original FOV" << std::endl;
            }
        }

        // Init spectra after camera HFOV has been finalized (including --focus-plant)
        // so the radiation camera is registered with the correct field of view.
        if (run_radiation && radiation_ptr) {
            RadiationModel &radiation = *radiation_ptr;
            init_spectral_data(context, cameralabel, radiation, plantarchitecture,
                                leafoptics, camera_setup, sampled_params,
                                args.run_multispectral, args.run_temperature, args.run_wue);
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
        
        // Render visualizer image after radiation trace to share context and prevent memory exhaustion
        if (g_debug_mode && !(run_vis || args.gui)) {
            std::cout << "Skipping visualizer image save for: " << filename
                      << " (renderer does not include vis)" << std::endl;
        }


        // Consolidated Visualizer rendering: Run if requested via --renderer vis/all or --gui
        if (run_vis || args.gui) {
            try {
                printGPUMemoryUsage("Before consolidated visualizer init");
                CameraProperties cam_prop = camera_setup.cam_prop;
                int vis_res_x = std::min(cam_prop.camera_resolution.x, 1920);
                int vis_res_y = std::min(cam_prop.camera_resolution.y, 1080);
                // In interactive GUI mode, create a real window (headless=false).
                // Otherwise use headless GLFW mode for reliable offscreen rendering on Linux.
                bool vis_headless = !args.gui;
                Visualizer vis(vis_res_x, vis_res_y, 0, true, vis_headless);
                vis.hideWatermark();
                vis.setLightDirection(sphere2cart(sun_dir));
                if (sampled_params["environment"]["sun"].value("shadow", true)) {
                    vis.setLightingModel(Visualizer::LIGHTING_PHONG_SHADOWED);
                } else {
                    vis.setLightingModel(Visualizer::LIGHTING_PHONG);
                }
                vis.buildContextGeometry(&context);
                vis.setBackgroundSkyTexture("plugins/visualizer/textures/SkyDome_clouds.jpg", 30);
                vis.setCameraPosition(camera_position, camera_lookat);
                float FOV_aspect_ratio = vis_res_x / float(vis_res_y);
                vis.setCameraFieldOfView(HFOVtoVFOV(cam_prop.HFOV, FOV_aspect_ratio));

                if (run_vis || args.gui) {
                    //vis.plotUpdate(true); // Comment out this line to make a faster rendering
                    std::string save_path = output_dir + "/" + filename + "_vis.jpeg";
                    vis.printWindow(save_path.c_str());
                    std::cout << "[SUCCESS] Saved Visualizer image to: " << save_path << std::endl;
                }

                if (args.gui) {
                    vis.plotInteractive();
                }
            } catch (const std::exception &e) {
                std::cerr << "Warning: failed to generate consolidated scientific visualizations: " << e.what() << std::endl;
            }
        }

        // Run radiation model
        if (run_radiation && radiation_ptr) {
          try {
            RadiationModel &radiation = *radiation_ptr;
            std::vector<std::string> bandlabels = {"red", "green", "blue"};
            if (args.run_multispectral) {
                bandlabels.push_back("NIR");
            }
            if (args.run_temperature) {
                bandlabels.push_back("LW");
            }
            radiation.enableCameraMetadata(cameralabel);
            // Change camera_RGB_00000.json to specific name like plot_20_13_0000_camera.json
            // update geometry and run radiation model
            if (g_debug_mode) std::cout << "[DEBUG] Updating radiation geometry..." << std::endl;
            radiation.updateGeometry();
            printSystemMemoryUsage("After updateGeometry");
            printGPUMemoryUsage("After updateGeometry");
            printGPUMemoryUsage("After updateGeometry");

            if (g_debug_mode) std::cout << "[DEBUG] Running radiation bands..." << std::endl;
            radiation.runBand(bandlabels);
            
            // Apply image corrections (brightness, contrast, saturation)
            // Note: Auto-exposure is already applied during runBand() based on camera exposure_mode
            // Use exposure_gain to fine-tune if needed (1.0 = no adjustment)
            // float exposure_gain = sampled_params["camera"]["sensor"].value("exposure_gain", 1.0f);
            radiation.applyCameraImageCorrections(cameralabel, "red", "green",
                "blue", 1.0, 1.0, 1.0);
            
            // save rendered RGB image with custom filename
            std::string image_file = radiation.writeCameraImage(
                cameralabel, {"red", "green", "blue"}, "RGB", output_dir, 0);

            // move image_file to output_dir/<filename>_rad.jpeg
            try {
                std::string target_path = output_dir + "/" + filename + "_rad.jpeg";
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
                std::cerr << "Warning: failed to move RGB image file: " << e.what() << std::endl;
            }

            if (args.run_multispectral) {
                std::string ms_file = radiation.writeCameraImage(
                    cameralabel, {"green", "red", "NIR"}, "multispectral", output_dir, 0);
                try {
                    std::string target_path = output_dir + "/" + filename + "_multispectral.jpeg";
                    if (ms_file != target_path) {
                        fs::path src(ms_file);
                        fs::path dst(target_path);
                        try {
                            fs::rename(src, dst);
                        } catch (const fs::filesystem_error &e) {
                            fs::copy_file(src, dst, fs::copy_options::overwrite_existing);
                            fs::remove(src);
                        }
                    }
                } catch (const std::exception &e) {
                    std::cerr << "Warning: failed to move multispectral image file: " << e.what() << std::endl;
                }
            }

            if (args.run_temperature || args.run_wue) {
                std::cout << "[DEBUG] Running biophysical simulation (Energy Balance)..." << std::endl;
                std::vector<uint> UUIDs_leaves;
                std::vector<uint> UUIDs_all_plant;
                std::vector<uint> all_crop_ids = plantarchitecture.getAllPlantIDs();
                for (uint id : all_crop_ids) {
                    std::vector<uint> leaf_obj_ids = plantarchitecture.getPlantLeafObjectIDs(id);
                    std::vector<uint> uuids_leaf = context.getObjectPrimitiveUUIDs(leaf_obj_ids);
                    UUIDs_leaves.insert(UUIDs_leaves.end(), uuids_leaf.begin(), uuids_leaf.end());

                    std::vector<uint> plant_obj_ids = plantarchitecture.getAllPlantObjectIDs(id);
                    std::vector<uint> uuids_plant = context.getObjectPrimitiveUUIDs(plant_obj_ids);
                    UUIDs_all_plant.insert(UUIDs_all_plant.end(), uuids_plant.begin(), uuids_plant.end());
                }
                std::vector<uint> all_UUIDs = context.getAllUUIDs();

                EnergyBalanceModel energybalance(&context);
                energybalance.addRadiationBand("red");
                energybalance.addRadiationBand("green");
                energybalance.addRadiationBand("blue");
                energybalance.addRadiationBand("LW");

                BLConductanceModel boundarylayerconductance(&context);
                boundarylayerconductance.setBoundaryLayerModel(UUIDs_ground, "Ground");
                boundarylayerconductance.setBoundaryLayerModel(UUIDs_leaves, "Pohlhausen");

                StomatalConductanceModel stomatalconductance(&context);
                BMFcoefficients bmfc;
                stomatalconductance.setModelCoefficients(bmfc);

                PhotosynthesisModel photosynthesis(&context);
                FarquharModelCoefficients photoparams;
                photosynthesis.setModelCoefficients(photoparams);
                photosynthesis.setModelType_Farquhar();

                // Set CIMIS ambient weather conditions directly to preserve main context spectrum and prevent VRAM OOM
                float air_temperature = 273.15 + 35; // 35 degrees C in Kelvin
                float air_humidity = 0.5f;       // 50% as decimal
                float wind_speed = 2.0f;         // 2 m/s

                context.setPrimitiveData(all_UUIDs, "air_temperature", air_temperature);
                context.setPrimitiveData(all_UUIDs, "air_humidity", air_humidity);
                context.setPrimitiveData(all_UUIDs, "wind_speed", wind_speed);

                // Initialize required thermal primitive data across all geometry to prevent missing value warnings
                context.setPrimitiveData(all_UUIDs, "emissivity_LW", 0.98f);
                context.setPrimitiveData(all_UUIDs, "emissivity_red", 0.0f);
                context.setPrimitiveData(all_UUIDs, "emissivity_green", 0.0f);
                context.setPrimitiveData(all_UUIDs, "emissivity_blue", 0.0f);
                context.setPrimitiveData(all_UUIDs, "reflectivity_LW", 0.02f);
                context.setPrimitiveData(all_UUIDs, "temperature", air_temperature);

                // Re-apply specific soil ground thermal properties
                context.setPrimitiveData(UUIDs_ground, "emissivity_LW", 0.95f);
                context.setPrimitiveData(UUIDs_ground, "reflectivity_LW", 0.05f);

                // Sum absorbed red, green, and blue solar radiation into radiation_flux_PAR
                // This is CRITICAL because Photosynthesis and Stomatal Conductance models specifically require "radiation_flux_PAR"
                for (uint UUID : UUIDs_all_plant) {
                    float q_red = 0, q_green = 0, q_blue = 0;
                    if (context.doesPrimitiveDataExist(UUID, "radiation_flux_red")) {
                        context.getPrimitiveData(UUID, "radiation_flux_red", q_red);
                    }
                    if (context.doesPrimitiveDataExist(UUID, "radiation_flux_green")) {
                        context.getPrimitiveData(UUID, "radiation_flux_green", q_green);
                    }
                    if (context.doesPrimitiveDataExist(UUID, "radiation_flux_blue")) {
                        context.getPrimitiveData(UUID, "radiation_flux_blue", q_blue);
                    }
                    context.setPrimitiveData(UUID, "radiation_flux_PAR", q_red + q_green + q_blue);
                }

                boundarylayerconductance.run();
                photosynthesis.run(UUIDs_leaves);
                stomatalconductance.run(UUIDs_leaves);

                // Force highly active transpiration (cool leaves) for visual dataset to ensure leaves are cooler than ground
                for (uint UUID : UUIDs_all_plant) {
                    float par = 0.f;
                    if (context.doesPrimitiveDataExist(UUID, "radiation_flux_PAR")) {
                        context.getPrimitiveData(UUID, "radiation_flux_PAR", par);
                    }
                    // Map PAR (0 to ~400 W/m2) to high conductance (0.05 to 0.6 mol/m2-s)
                    float gs = 0.05f + (par / 400.0f) * 0.55f;
                    if (gs > 0.6f) gs = 0.6f;
                    context.setPrimitiveData(UUID, "moisture_conductance", gs);
                    
                    // The Pohlhausen boundary layer model may compute a very small conductance if wind is low or object_length is missing.
                    // This creates a bottleneck (gM becomes tiny regardless of gS).
                    // Force boundary layer conductance to be high to allow maximum evaporation.
                    context.setPrimitiveData(UUID, "boundarylayer_conductance", 2.0f);
                    
                    // Force stomatal sidedness to amphistomatous (0.5) to allow evaporation from both sides of the leaf.
                    context.setPrimitiveData(UUID, "stomatal_sidedness", 0.5f);
                }

                energybalance.run();
                std::cout << "[SUCCESS] Energy Balance simulation completed successfully." << std::endl;
                
                // Debug: Calculate and print average temperatures to verify cooling
                float avg_leaf_temp = 0.f;
                int leaf_count = 0;
                for (uint UUID : UUIDs_leaves) {
                    float t = 0.f;
                    if (context.doesPrimitiveDataExist(UUID, "temperature")) {
                        context.getPrimitiveData(UUID, "temperature", t);
                        avg_leaf_temp += t;
                        leaf_count++;
                    }
                }
                if (leaf_count > 0) avg_leaf_temp /= leaf_count;
                
                float avg_ground_temp = 0.f;
                int ground_count = 0;
                for (uint UUID : UUIDs_ground) {
                    float t = 0.f;
                    if (context.doesPrimitiveDataExist(UUID, "temperature")) {
                        context.getPrimitiveData(UUID, "temperature", t);
                        avg_ground_temp += t;
                        ground_count++;
                    }
                }
                if (ground_count > 0) avg_ground_temp /= ground_count;
                
                std::cout << "[DEBUG] Average Leaf Temp: " << avg_leaf_temp << " K (" << (avg_leaf_temp - 273.15f) << " C)" << std::endl;
                std::cout << "[DEBUG] Average Ground Temp: " << avg_ground_temp << " K (" << (avg_ground_temp - 273.15f) << " C)" << std::endl;
            }

            if (args.run_temperature) {
                std::string temp_file = radiation.writeCameraImage(
                    cameralabel, {"LW"}, "temperature", output_dir, 0);
                try {
                    std::string target_path = output_dir + "/" + filename + "_temperature.jpeg";
                    if (temp_file != target_path) {
                        fs::path src(temp_file);
                        fs::path dst(target_path);
                        try {
                            fs::rename(src, dst);
                        } catch (const fs::filesystem_error &e) {
                            fs::copy_file(src, dst, fs::copy_options::overwrite_existing);
                            fs::remove(src);
                        }
                    }
                } catch (const std::exception &e) {
                    std::cerr << "Warning: failed to move LW radiation image file: " << e.what() << std::endl;
                }
            }

            if (args.run_depth) {
                // Export normalized depth map image (cutoff max 5.5 meters for 5.0m altitude drone cameras)
                radiation.writeNormDepthImage(cameralabel, "depth", 5.5f, output_dir + "/", 0);
                try {
                    std::string depth_file = output_dir + "/" + cameralabel + "_depth_00000.jpeg";
                    std::string target_path = output_dir + "/" + filename + "_depth.jpeg";
                    if (fs::exists(depth_file)) {
                        fs::path src(depth_file);
                        fs::path dst(target_path);
                        try {
                            fs::rename(src, dst);
                        } catch (const fs::filesystem_error &e) {
                            fs::copy_file(src, dst, fs::copy_options::overwrite_existing);
                            fs::remove(src);
                        }
                    }
                } catch (const std::exception &e) {
                    std::cerr << "Warning: failed to move depth image file: " << e.what() << std::endl;
                }
            }

            if (args.run_wue) {
                std::cout << "[DEBUG] Calculating WUE and rendering image via GPU raytracing..." << std::endl;
                std::vector<uint> UUIDs_leaves;
                std::vector<uint> all_crop_ids = plantarchitecture.getAllPlantIDs();
                for (uint id : all_crop_ids) {
                    std::vector<uint> leaf_obj_ids = plantarchitecture.getPlantLeafObjectIDs(id);
                    std::vector<uint> uuids_leaf = context.getObjectPrimitiveUUIDs(leaf_obj_ids);
                    UUIDs_leaves.insert(UUIDs_leaves.end(), uuids_leaf.begin(), uuids_leaf.end());
                }
                for (uint UUID : UUIDs_leaves) {
                    float E = 0.0f, A = 0.0f, WUE = 0.0f;
                    context.getPrimitiveData(UUID, "latent_flux", E);
                    context.getPrimitiveData(UUID, "net_photosynthesis", A);
                    float transpiration = E / 44000.0f * 1000.0f; // mmol H2O / m^2 / sec
                    if (transpiration > 1e-6f) {
                        WUE = A / transpiration;
                    } else {
                        WUE = 0.0f;
                    }
                    context.setPrimitiveData(UUID, "WUE", WUE);
                    context.setPrimitiveData(UUID, "emission_wue_band", WUE);
                    context.setPrimitiveData(UUID, "reflectivity_wue_band", 0.0f);
                    context.setPrimitiveData(UUID, "transmissivity_wue_band", 0.0f);
                }
                std::cout << "[SUCCESS] WUE calculated for " << UUIDs_leaves.size() << " leaves." << std::endl;

                radiation.runBand("wue_band");
                std::string wue_file = radiation.writeCameraImage(cameralabel, {"wue_band"}, "wue_raw", output_dir, 0);
                try {
                    std::string target_path = output_dir + "/" + filename + "_wue_raw.jpeg";
                    if (wue_file != target_path) {
                        fs::path src(wue_file);
                        fs::path dst(target_path);
                        try {
                            fs::rename(src, dst);
                        } catch (const fs::filesystem_error &e) {
                            fs::copy_file(src, dst, fs::copy_options::overwrite_existing);
                            fs::remove(src);
                        }
                    }
                } catch (const std::exception &e) {
                    std::cerr << "Warning: failed to move WUE raw image file: " << e.what() << std::endl;
                }
            }


    

            // Export bounding boxes and segmentation masks in COCO format
            radiation.writeImageBoundingBoxes(cameralabel, {"plant", "flower", "pod"},
                                              {0, 1, 2}, output_dir + "/" + filename +"_boxes", cameralabel+"_classes.txt",
                                              output_dir + '/');

            radiation.writeImageSegmentationMasks(
                cameralabel, {"plant", "flower", "pod"}, {0, 1, 2},
                output_dir + '/' + filename + "_masks.json", image_file);

            // auto-calibrate camera using colorboard reference values with
            // quality report (only if user enabled calibration)
            std::string corrected_image;
            if (args.calibrate_color) {
                corrected_image = radiation.autoCalibrateCameraImage(
                    cameralabel, "red", "green", "blue",
                    output_dir + '/' + filename + ".jpeg", true);
            }

            // Rename automatically created camera_RGB_00000.json to custom name
            try {
                std::string default_camera_file = output_dir + "/" + cameralabel + "_RGB_00000.json";
                std::string target_camera_path = output_dir + "/" + filename + "_camera.json";
                
                if (fs::exists(default_camera_file)) {
                    fs::path src(default_camera_file);
                    fs::path dst(target_camera_path);
                    // Try rename (move), overwriting if target exists
                    try {
                        fs::rename(src, dst);
                    } catch (const fs::filesystem_error &e) {
                        // Fallback to copy + remove if rename fails
                        fs::copy_file(src, dst, fs::copy_options::overwrite_existing);
                        fs::remove(src);
                    }
                    if (g_debug_mode) {
                        std::cout << "[DEBUG] Renamed camera metadata file to: " << target_camera_path << std::endl;
                    }
                }
            } catch (const std::exception &e) {
                std::cerr << "Warning: failed to rename camera metadata file: " << e.what() << std::endl;
            }
          } catch (const std::exception &e) {
              std::cerr << "Warning: Radiation GPU model skipped (Visualizer & XML mode): " << e.what() << std::endl;
          }
        }
    }

    std::cout << "\nCompleted all " << num_iterations
              << " iterations. Parameters saved to individual JSON files."
              << std::endl;

     return 0;
}