#include "PlantArchitecture.h"
#include "Visualizer.h"
#include "RadiationModel.h"
#include "json.hpp"

#include <filesystem>
#include <fstream>
#include <random>
#include <iomanip>
#include <sstream>

using namespace helios;
using json = nlohmann::json;

namespace fs = std::filesystem;

// Function to sample a value based on sampling method, min, and max
template<typename T>
T sampleValue(const json& param, std::mt19937& rng) {
    std::string sampling = param["sampling"];
    T min_val = param["min"];
    T max_val = param["max"];

    if (sampling == "uniform") {
        if constexpr (std::is_integral_v<T>) {
            std::uniform_int_distribution<T> dist(min_val, max_val);
            return dist(rng);
        } else {
            std::uniform_real_distribution<T> dist(min_val, max_val);
            return dist(rng);
        }
    }
    // Add other sampling methods here if needed (normal, etc.)
    return min_val; // fallback
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

// choosing plant architecture with most visual differences
// parameters: plant count, plant age, leaf pitch, number of flowers

int main(){
    // Number of iterations to run
    const int num_iterations = 300; // Change this to desired number of images

    // Initialize random number generator
    std::random_device rd;
    std::mt19937 rng(rd());

    // Load parameters from JSON file once
    json json_params = loadParametersFromJson("/home/eranario/CLionProjects/Helios/projects/syntheticdata_sample_test/params.json");

    for (int iteration = 0; iteration < num_iterations; ++iteration) {
        std::cout << "\n=== Iteration " << (iteration + 1) << " of " << num_iterations << " ===" << std::endl;

        // Create new context for each iteration
        Context context;

        // Sample values from JSON parameters
        int plant_count = sampleValue<int>(json_params["plantarchitecture"]["initialize"]["plant_count"], rng);
        float plant_age = sampleValue<float>(json_params["plantarchitecture"]["initialize"]["plant_age"], rng);
        float plant_spacing_x = sampleValue<float>(json_params["plantarchitecture"]["initialize"]["plant_spacing_x"], rng);
        float plant_spacing_y = sampleValue<float>(json_params["plantarchitecture"]["initialize"]["plant_spacing_y"], rng);
        float leaf_pitch = sampleValue<float>(json_params["plantarchitecture"]["phytomer_parameters"]["leaf_pitch"], rng);
        float flower_bud_break_probability = sampleValue<float>(json_params["plantarchitecture"]["flower_bud_break_probability"], rng);

        // Sample camera properties from JSON parameters
        float camera_height = sampleValue<float>(json_params["cameraproperties"]["camera_height"], rng);
        float focal_plane_distance_diff = sampleValue<float>(json_params["cameraproperties"]["focal_plane_distance_difference"], rng);
        float lens_diameter = sampleValue<float>(json_params["cameraproperties"]["lens_diameter"], rng);
        float hfov = sampleValue<float>(json_params["cameraproperties"]["HFOV"], rng);

        // Sample camera positioning parameters
        float distance_from_center = sampleValue<float>(json_params["cameraproperties"]["camera_positioning"]["distance_from_center"], rng);
        float azimuth_angle = sampleValue<float>(json_params["cameraproperties"]["camera_positioning"]["azimuth_angle"], rng);
        float lookat_offset_x = sampleValue<float>(json_params["cameraproperties"]["camera_positioning"]["lookat_offset_x"], rng);
        float lookat_offset_y = sampleValue<float>(json_params["cameraproperties"]["camera_positioning"]["lookat_offset_y"], rng);
        float lookat_offset_z = sampleValue<float>(json_params["cameraproperties"]["camera_positioning"]["lookat_offset_z"], rng);

        // Create filename with zero-padded iteration number
        std::stringstream filename_stream;
        filename_stream << std::setw(4) << std::setfill('0') << iteration;
        std::string filename = filename_stream.str();

        // Create a new JSON object to store the sampled parameters
        json sampled_params;
        sampled_params["plantarchitecture"]["initialize"]["plant_count"] = plant_count;
        sampled_params["plantarchitecture"]["initialize"]["plant_age"] = plant_age;
        sampled_params["plantarchitecture"]["initialize"]["plant_spacing_x"] = plant_spacing_x;
        sampled_params["plantarchitecture"]["initialize"]["plant_spacing_y"] = plant_spacing_y;
        sampled_params["plantarchitecture"]["phytomer_parameters"]["leaf_pitch"] = leaf_pitch;
        sampled_params["plantarchitecture"]["flower_bud_break_probability"] = flower_bud_break_probability;
        sampled_params["cameraproperties"]["camera_height"] = camera_height;
        sampled_params["cameraproperties"]["focal_plane_distance_difference"] = focal_plane_distance_diff;
        sampled_params["cameraproperties"]["lens_diameter"] = lens_diameter;
        sampled_params["cameraproperties"]["HFOV"] = hfov;
        sampled_params["cameraproperties"]["camera_positioning"]["distance_from_center"] = distance_from_center;
        sampled_params["cameraproperties"]["camera_positioning"]["azimuth_angle"] = azimuth_angle;
        sampled_params["cameraproperties"]["camera_positioning"]["lookat_offset_x"] = lookat_offset_x;
        sampled_params["cameraproperties"]["camera_positioning"]["lookat_offset_y"] = lookat_offset_y;
        sampled_params["cameraproperties"]["camera_positioning"]["lookat_offset_z"] = lookat_offset_z;

        // Save the sampled parameters to a JSON file
        std::ofstream params_file("/group/jmearlesgrp/data/plant-simulation-to-traits/synthetic_data/sample_300_100225/" + filename + "_params.json");
        params_file << std::setw(4) << sampled_params << std::endl;
        params_file.close();

        // Print sampled values for debugging
        std::cout << "Sampled parameters from JSON:" << std::endl;
        std::cout << "  Filename: " << filename << std::endl;
        std::cout << "  Plant count: " << plant_count << std::endl;
        std::cout << "  Plant age: " << plant_age << std::endl;
        std::cout << "  Plant spacing (x, y): " << plant_spacing_x << ", " << plant_spacing_y << std::endl;
        std::cout << "  Leaf pitch: " << leaf_pitch << std::endl;
        std::cout << "  Flower bud break probability: " << flower_bud_break_probability << std::endl;
        std::cout << "  Camera height: " << camera_height << std::endl;
        std::cout << "  Focal plane distance difference: " << focal_plane_distance_diff << std::endl;
        std::cout << "  Lens diameter: " << lens_diameter << std::endl;
        std::cout << "  HFOV: " << hfov << std::endl;
        std::cout << "  Distance from center: " << distance_from_center << std::endl;
        std::cout << "  Azimuth angle: " << azimuth_angle << std::endl;
        std::cout << "  Lookat offset (x,y,z): " << lookat_offset_x << ", " << lookat_offset_y << ", " << lookat_offset_z << std::endl;

        // Fixed ground size of 50x50 meters
        float ground_size_x = 10.0f;
        float ground_size_y = 10.0f;

        std::cout << "Ground configuration:" << std::endl;
        std::cout << "  Ground size (x, y): " << ground_size_x << ", " << ground_size_y << std::endl;

        // load dirt texture with fixed size
        std::vector<uint> UUIDs_ground = context.addTile(
            make_vec3(0,0,0), make_vec2(ground_size_x, ground_size_y), make_SphericalCoord(0,0), make_int2(200, 200),
            "plugins/visualizer/textures/dirt.jpg", make_int2(10,10)
        );
        context.setPrimitiveData(UUIDs_ground, "twosided_flag", 0u);

        PlantArchitecture plantarchitecture(&context);
        plantarchitecture.loadPlantModelFromLibrary("cowpea");

        std::map<std::string, ShootParameters> params = plantarchitecture.getCurrentShootParameters();

        // update leaf pitch and peduncle length
        params.at("trifoliate").phytomer_parameters.leaf.pitch = leaf_pitch;
        params.at("trifoliate").flower_bud_break_probability = flower_bud_break_probability;
        plantarchitecture.updateCurrentShootParameters("trifoliate", params.at("trifoliate"));

        // plant count and age can be changed here
        std::vector<uint> plant_IDs = plantarchitecture.buildPlantCanopyFromLibrary(
            make_vec3(0, 0, 0), make_vec2(plant_spacing_x, plant_spacing_y),
            make_int2(plant_count, 1), static_cast<int>(plant_age)
        );
        std::vector<uint> UUIDs_plants = plantarchitecture.getAllUUIDs();

        // load color and reflectivity data
        context.loadXML( "plugins/radiation/spectral_data/color_board/DGK_DKK_colorboard.xml", true );
        context.loadXML("plugins/radiation/spectral_data/leaf_surface_spectral_library.xml");
        context.loadXML("plugins/radiation/spectral_data/soil_surface_spectral_library.xml");
        context.renameGlobalData("ColorReference_DGK_08","spectrum_yellow");
        context.renameGlobalData("ColorReference_DGK_09","spectrum_green");

        // assign colors to each object
        context.setPrimitiveData(UUIDs_plants, "reflectivity_spectrum", "grape_leaf_reflectivity_0000");
        context.setPrimitiveData(UUIDs_plants, "transmissivity_spectrum", "grape_leaf_transmissivity_0000");
        context.setPrimitiveData(UUIDs_ground, "reflectivity_spectrum", "soil_reflectivity_0000");

        // set specular properties for realistic shading
        context.setPrimitiveData(UUIDs_plants, "specular_exponent", 10.f);
        context.setPrimitiveData(UUIDs_ground, "specular_exponent", 10.f);

        // prepare custom yellow color
        RadiationModel radiation(&context);
        radiation.blendSpectra("reflectivity_flower_cowpea_closed", {"spectrum_yellow", "spectrum_green"}, {0.35, 0.65});

        // get unique labels for flowers
        uint counter = 0;
        for (uint& id : plant_IDs) {
            std::vector<uint> IDs_flower = plantarchitecture.getPlantFlowerObjectIDs(id);

            for (uint& id_flower : IDs_flower) {
                std::vector<uint> uuids_flower = context.getObjectPrimitiveUUIDs(id_flower);
                context.setPrimitiveData(uuids_flower, "reflectivity_spectrum", "reflectivity_flower_cowpea_closed");
                context.setPrimitiveData(uuids_flower, "flower", counter);
                counter++;
            }
        }

        // add color calibration target (optional)
        CameraCalibration calibration(&context);
        calibration.addCalibriteColorboard(make_vec3(0,0.75,0.001), 0.025);

        // set up sun lighting
        SphericalCoord sun_dir = make_SphericalCoord(deg2rad(45), -deg2rad(45));
        uint sunID = radiation.addSunSphereRadiationSource(sun_dir);
        radiation.setSourceSpectrum(sunID, "solar_spectrum_ASTMG173");

        // create RGB radiation bands
        radiation.addRadiationBand("red");
        radiation.disableEmission("red");
        radiation.setDiffuseRadiationExtinctionCoeff("red", 0.3f, sun_dir);
        radiation.setScatteringDepth("red", 3); // Increased from 3 to 5 for smoother shadows

        radiation.copyRadiationBand("red", "green");
        radiation.copyRadiationBand("red", "blue");

        std::vector<std::string> bandlabels = {"red", "green", "blue"};
        radiation.setDiffuseSpectrum( bandlabels, "solar_spectrum_ASTMG173");

        std::string cameralabel = "flowercam";

        // camera params
        CameraProperties cameraproperties;
        cameraproperties.focal_plane_distance = camera_height - focal_plane_distance_diff; //focus on center of scene
        cameraproperties.lens_diameter = lens_diameter; //make it small so it will be in focus
        cameraproperties.HFOV = hfov;
        vec3 camera_position(0, 0, 0);
        vec3 camera_lookat(0, 0, 0);

        // Calculate plant canopy center based on plant positioning
        vec3 canopy_center = make_vec3(0, 0, 0); // Plants are positioned at origin

        // Convert azimuth angle from degrees to radians
        float azimuth_rad = deg2rad(azimuth_angle);

        // Calculate camera position based on plant canopy center
        camera_position.x = canopy_center.x + distance_from_center * cos(azimuth_rad);
        camera_position.y = canopy_center.y + distance_from_center * sin(azimuth_rad);
        camera_position.z = camera_height;

        // Calculate camera lookat point (slightly offset from canopy center)
        camera_lookat.x = canopy_center.x + lookat_offset_x;
        camera_lookat.y = canopy_center.y + lookat_offset_y;
        camera_lookat.z = canopy_center.z + lookat_offset_z;

        std::cout << "Calculated camera positioning:" << std::endl;
        std::cout << "  Camera position: (" << camera_position.x << ", " << camera_position.y << ", " << camera_position.z << ")" << std::endl;
        std::cout << "  Camera lookat: (" << camera_lookat.x << ", " << camera_lookat.y << ", " << camera_lookat.z << ")" << std::endl;

        // add the camera to the radiation model
        radiation.addRadiationCamera(cameralabel, bandlabels, camera_position, camera_lookat, cameraproperties, 100);

        // set camera spectral response to simulate iPhone camera
        context.loadXML( "plugins/radiation/spectral_data/camera_spectral_library.xml", true);
        radiation.setCameraSpectralResponse(cameralabel, "red", "Basler_acA2500-20gc_red");
        radiation.setCameraSpectralResponse(cameralabel, "green","Basler_acA2500-20gc_green");
        radiation.setCameraSpectralResponse(cameralabel, "blue", "Basler_acA2500-20gc_blue");

        // update geometry and run radiation model
        radiation.updateGeometry();
        radiation.runBand(bandlabels);

        // process image using standard pipeline
        radiation.applyImageProcessingPipeline("flowercam", "red", "green", "blue");

        // save rendered RGB image with custom filename
        std::string image_file = radiation.writeCameraImage(cameralabel, bandlabels, "RGB", "/group/jmearlesgrp/data/plant-simulation-to-traits/synthetic_data/sample_300_100225/", iteration);
        std::string image_base = fs::path(image_file).stem().string();

        // export bounding boxes and segmentation masks in COCO format
        radiation.writeImageSegmentationMasks( cameralabel, {"flower"}, {0}, "/group/jmearlesgrp/data/plant-simulation-to-traits/synthetic_data/sample_300_100225/" + filename + "_labels.json", image_file );

        // auto-calibrate camera using colorboard reference values with quality report
        std::string corrected_image = radiation.autoCalibrateCameraImage("flowercam", "red", "green", "blue", "/group/jmearlesgrp/data/plant-simulation-to-traits/synthetic_data/sample_300_100225/" + filename + ".jpeg", true);

        // Delete the uncalibrated image after calibrated version is created
        try {
            if (fs::exists(image_file)) {
                fs::remove(image_file);
                std::cout << "  Deleted uncalibrated image: " << image_file << std::endl;
            }
        } catch (const std::exception& e) {
            std::cout << "  Warning: Could not delete uncalibrated image " << image_file << ": " << e.what() << std::endl;
        }

        std::cout << "Completed iteration " << (iteration + 1) << ", saved as: " << filename << std::endl;
    }

    std::cout << "\nCompleted all " << num_iterations << " iterations. Parameters saved to individual JSON files." << std::endl;

    // Initialize visualizer (only once at the end if needed)
    Visualizer vis(1000);

    return 0;
}