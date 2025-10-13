#include "PlantArchitecture.h"
#include "Visualizer.h"
#include "RadiationModel.h"
#include "json.hpp"
#include "main.h"

#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <random>
#include <sstream>

using namespace helios;
namespace fs = std::filesystem;

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

SampledParameters sampleParameters(const json& json_params, std::mt19937& rng) {

    SampledParameters sampled{};

    // plant
    sampled.plant = json_params["plant"];

    // ground
    sampled.ground_size_x =  sampleValue<int>(json_params["ground"]["size_x"], rng);
    sampled.ground_size_y = sampleValue<int>(json_params["ground"]["size_y"], rng);
    sampled.texture_file = json_params["ground"]["texture_file"];

    // sun position
    sampled.elevation_degrees = sampleValue<float>(json_params["sun_position"]["elevation_degrees"], rng);
    sampled.azimuth_degrees = sampleValue<float>(json_params["sun_position"]["azimuth_degrees"], rng);

    // plant architecture
    sampled.plant_count = sampleValue<int>(json_params["plantarchitecture"]["initialize"]["plant_count"], rng);
    sampled.num_columns = sampleValue<int>(json_params["plantarchitecture"]["initialize"]["num_columns"], rng);
    sampled.plant_age = sampleValue<float>(json_params["plantarchitecture"]["initialize"]["plant_age"], rng);
    sampled.plant_spacing_x = sampleValue<float>(json_params["plantarchitecture"]["initialize"]["plant_spacing_x"], rng);
    sampled.plant_spacing_y = sampleValue<float>(json_params["plantarchitecture"]["initialize"]["plant_spacing_y"], rng);
    sampled.leaf_pitch = sampleValue<float>(json_params["plantarchitecture"]["phytomer_parameters"]["leaf_pitch"], rng);
    sampled.flower_bud_break_probability = sampleValue<float>(json_params["plantarchitecture"]["flower_bud_break_probability"], rng);

    // camera properties
    sampled.camera_height = sampleValue<float>(json_params["cameraproperties"]["camera_height"], rng);
    sampled.focal_plane_distance_difference = sampleValue<float>(json_params["cameraproperties"]["focal_plane_distance_difference"], rng);
    sampled.lens_diameter = sampleValue<float>(json_params["cameraproperties"]["lens_diameter"], rng);
    sampled.hfov = sampleValue<float>(json_params["cameraproperties"]["HFOV"], rng);
    sampled.distance_from_center = sampleValue<float>(json_params["cameraproperties"]["camera_positioning"]["distance_from_center"], rng);
    sampled.azimuth_angle = sampleValue<float>(json_params["cameraproperties"]["camera_positioning"]["azimuth_angle"], rng);
    sampled.lookat_offset_x = sampleValue<float>(json_params["cameraproperties"]["camera_positioning"]["lookat_offset_x"], rng);
    sampled.lookat_offset_y = sampleValue<float>(json_params["cameraproperties"]["camera_positioning"]["lookat_offset_y"], rng);
    sampled.lookat_offset_z = sampleValue<float>(json_params["cameraproperties"]["camera_positioning"]["lookat_offset_z"], rng);

    // radiation model
    sampled.colorboard = json_params["radiationmodel"]["colorboard"];
    sampled.leaf_surface_spectral_data = json_params["radiationmodel"]["leaf_surface_spectral_data"]["file"];
    sampled.leaf_reflectivity = json_params["radiationmodel"]["leaf_surface_spectral_data"]["reflectivity"];
    sampled.leaf_transmissivity = json_params["radiationmodel"]["leaf_surface_spectral_data"]["transmissivity"];
    sampled.soil_surface_spectral_data = json_params["radiationmodel"]["soil_surface_spectral_data"]["file"];
    sampled.soil_reflectivity = json_params["radiationmodel"]["soil_surface_spectral_data"]["reflectivity"];
    sampled.camera_spectral_data = json_params["radiationmodel"]["camera_spectral_data"]["file"];
    sampled.camera_type = json_params["radiationmodel"]["camera_spectral_data"]["camera_type"];

    return sampled;
}

json buildSampledParametersJson(const SampledParameters& sampled) {

    json sampled_params;

    // plant
    sampled_params["plant"] = sampled.plant;

    // ground
    sampled_params["ground"]["size_x"] = sampled.ground_size_x;
    sampled_params["ground"]["size_y"] = sampled.ground_size_y;
    sampled_params["ground"]["texture_file"] = sampled.texture_file;

    // sun direction
    sampled_params["sun_position"]["elevation_degrees"] = sampled.elevation_degrees;
    sampled_params["sun_position"]["azimuth_degrees"] = sampled.azimuth_degrees;

    // plant architecture
    sampled_params["plantarchitecture"]["initialize"]["plant_count"] = sampled.plant_count;
    sampled_params["plantarchitecture"]["initialize"]["num_columns"] = sampled.num_columns;
    sampled_params["plantarchitecture"]["initialize"]["plant_age"] = sampled.plant_age;
    sampled_params["plantarchitecture"]["initialize"]["plant_spacing_x"] = sampled.plant_spacing_x;
    sampled_params["plantarchitecture"]["initialize"]["plant_spacing_y"] = sampled.plant_spacing_y;
    sampled_params["plantarchitecture"]["phytomer_parameters"]["leaf_pitch"] = sampled.leaf_pitch;
    sampled_params["plantarchitecture"]["flower_bud_break_probability"] = sampled.flower_bud_break_probability;

    // camera properties
    sampled_params["cameraproperties"]["camera_height"] = sampled.camera_height;
    sampled_params["cameraproperties"]["focal_plane_distance_difference"] = sampled.focal_plane_distance_difference;
    sampled_params["cameraproperties"]["lens_diameter"] = sampled.lens_diameter;
    sampled_params["cameraproperties"]["HFOV"] = sampled.hfov;
    sampled_params["cameraproperties"]["camera_positioning"]["distance_from_center"] = sampled.distance_from_center;
    sampled_params["cameraproperties"]["camera_positioning"]["azimuth_angle"] = sampled.azimuth_angle;
    sampled_params["cameraproperties"]["camera_positioning"]["lookat_offset_x"] = sampled.lookat_offset_x;
    sampled_params["cameraproperties"]["camera_positioning"]["lookat_offset_y"] = sampled.lookat_offset_y;
    sampled_params["cameraproperties"]["camera_positioning"]["lookat_offset_z"] = sampled.lookat_offset_z;

    // radiation model
    sampled_params["radiationmodel"]["colorboard"] = sampled.colorboard;
    sampled_params["radiationmodel"]["leaf_surface_spectral_data"]["file"] = sampled.leaf_surface_spectral_data;
    sampled_params["radiationmodel"]["leaf_surface_spectral_data"]["reflectivity"] = sampled.leaf_reflectivity;
    sampled_params["radiationmodel"]["leaf_surface_spectral_data"]["transmissivity"] = sampled.leaf_transmissivity;
    sampled_params["radiationmodel"]["soil_surface_spectral_data"]["file"] = sampled.soil_surface_spectral_data;
    sampled_params["radiationmodel"]["soil_surface_spectral_data"]["reflectivity"] = sampled.soil_reflectivity;
    sampled_params["radiationmodel"]["camera_spectral_data"]["file"] = sampled.camera_spectral_data;
    sampled_params["radiationmodel"]["camera_spectral_data"]["camera_type"] = sampled.camera_type;

    return sampled_params;
}

int main(){

    // load parameters
    json json_params = loadParametersFromJson("../params.json");

    // number of data samples
    const int num_iterations = json_params["iterations"]; // Change this to desired number of images

    // prepare output dir
    std::string output_dir = json_params.value("output_directory", "output");
    if (!fs::exists(output_dir)) {
        fs::create_directories(output_dir);
    }
    std::cout << "Output directory: " << output_dir << std::endl;

    std::random_device rd;
    std::mt19937 rng(rd());

    for (int iteration = 0; iteration < num_iterations; ++iteration) {
        std::cout << "\n=== Iteration " << (iteration + 1) << " of " << num_iterations << " ===" << std::endl;

        Context context;

        // sample parameters
        SampledParameters sampled = sampleParameters(json_params, rng);
        const auto& s = sampled;

        // filename with zero-padded iteration number
        std::stringstream filename_stream;
        filename_stream << std::setw(4) << std::setfill('0') << iteration;
        std::string filename = filename_stream.str();

        // JSON object to store the sampled parameters
        json sampled_params = buildSampledParametersJson(sampled);

        // save sampled parameters
        std::ofstream params_file(output_dir + "/" + filename + "_params.json");
        params_file << std::setw(4) << sampled_params << std::endl;
        params_file.close();

        // load dirt texture with fixed size
        // default: plugins/visualizer/textures/dirt.jpg
        std::vector<uint> UUIDs_ground = context.addTile(
            make_vec3(0,0,0), make_vec2(s.ground_size_x, s.ground_size_y), make_SphericalCoord(0,0), make_int2(200, 200),
            s.texture_file.c_str(), make_int2(10,10)
        );
        context.setPrimitiveData(UUIDs_ground, "twosided_flag", 0u);

        PlantArchitecture plantarchitecture(&context);
        plantarchitecture.loadPlantModelFromLibrary(s.plant);

        std::map<std::string, ShootParameters> params = plantarchitecture.getCurrentShootParameters();

        // update leaf pitch and peduncle length
        params.at("trifoliate").phytomer_parameters.leaf.pitch = s.leaf_pitch;
        params.at("trifoliate").flower_bud_break_probability = s.flower_bud_break_probability;

        // update leaf and ground textures
        params.at("trifoliate").phytomer_parameters.leaf.prototype.prototype_function = CowpeaLeafPrototype_trifoliate_OBJ;

        // apply updated parameters
        plantarchitecture.updateCurrentShootParameters("trifoliate", params.at("trifoliate"));

        // plant count and age can be changed here
        std::vector<uint> plant_IDs = plantarchitecture.buildPlantCanopyFromLibrary(
            make_vec3(0, 0, 0), make_vec2(s.plant_spacing_x, s.plant_spacing_y),
            make_int2(s.plant_count, s.num_columns), static_cast<int>(s.plant_age)
        );
        std::vector<uint> UUIDs_plants = plantarchitecture.getAllUUIDs();

        // load color and reflectivity data
        context.loadXML( s.colorboard.c_str(), true );
        context.loadXML( s.leaf_surface_spectral_data.c_str(), true );
        context.loadXML( s.soil_surface_spectral_data.c_str(), true );
        context.renameGlobalData("ColorReference_DGK_08", "spectrum_yellow");
        context.renameGlobalData("ColorReference_DGK_09", "spectrum_green");

        // assign colors to each object
        context.setPrimitiveData(UUIDs_plants, "reflectivity_spectrum", s.leaf_reflectivity);
        context.setPrimitiveData(UUIDs_plants, "transmissivity_spectrum", s.leaf_transmissivity);
        // context.setPrimitiveData(UUIDs_ground, "reflectivity_spectrum", s.soil_reflectivity);

        // set specular properties for realistic shading
        context.setPrimitiveData(UUIDs_plants, "specular_exponent", 10.f);
        // context.setPrimitiveData(UUIDs_ground, "specular_exponent", 10.f);

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
        SphericalCoord sun_dir = make_SphericalCoord(deg2rad(s.elevation_degrees), -deg2rad(s.azimuth_degrees));
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

        std::string cameralabel = "camera";

        // camera params
        CameraProperties cameraproperties;
        cameraproperties.focal_plane_distance = s.camera_height - s.focal_plane_distance_difference; //focus on center of scene
        cameraproperties.lens_diameter = s.lens_diameter; //make it small so it will be in focus
        cameraproperties.HFOV = s.hfov;
        vec3 camera_position(0, 0, 0);
        vec3 camera_lookat(0, 0, 0);

        // Calculate plant canopy center based on plant positioning
        vec3 canopy_center = make_vec3(0, 0, 0); // Plants are positioned at origin

        // Convert azimuth angle from degrees to radians
        float azimuth_rad = deg2rad(s.azimuth_angle);

        // Calculate camera position based on plant canopy center
        camera_position.x = canopy_center.x + s.distance_from_center * cos(azimuth_rad);
        camera_position.y = canopy_center.y + s.distance_from_center * sin(azimuth_rad);
        camera_position.z = s.camera_height;

        // Calculate camera lookat point (slightly offset from canopy center)
        camera_lookat.x = canopy_center.x + s.lookat_offset_x;
        camera_lookat.y = canopy_center.y + s.lookat_offset_y;
        camera_lookat.z = canopy_center.z + s.lookat_offset_z;

        // add the camera to the radiation model
        radiation.addRadiationCamera(cameralabel, bandlabels, camera_position, camera_lookat, cameraproperties, 1000);

        // set camera spectral response to simulate iPhone camera
        context.loadXML( "plugins/radiation/spectral_data/camera_spectral_library.xml", true);
        radiation.setCameraSpectralResponse(cameralabel, "red", (s.camera_type + "_red").c_str());
        radiation.setCameraSpectralResponse(cameralabel, "green", (s.camera_type + "_green").c_str());
        radiation.setCameraSpectralResponse(cameralabel, "blue", (s.camera_type + "_blue").c_str());

        // update geometry and run radiation model
        radiation.updateGeometry();
        radiation.runBand(bandlabels);

        // process image using standard pipeline
        radiation.applyImageProcessingPipeline(cameralabel, "red", "green", "blue");

        // save rendered RGB image with custom filename
        std::string image_file = radiation.writeCameraImage(cameralabel, bandlabels, "RGB", output_dir, iteration);
        std::string image_base = fs::path(image_file).stem().string();

        // export bounding boxes and segmentation masks in COCO format
        radiation.writeImageSegmentationMasks( cameralabel, {"flower"}, {0}, output_dir + '/' + filename + "_labels.json", image_file );

        // auto-calibrate camera using colorboard reference values with quality report
        std::string corrected_image = radiation.autoCalibrateCameraImage(cameralabel, "red", "green", "blue", output_dir + '/' + filename + ".jpeg", true);

        // Delete the uncalibrated image after calibrated version is created
        try {
            if (fs::exists(image_file)) {
                fs::remove(image_file);
            }
        } catch (const std::exception& e) {
            std::cout << "  Warning: Could not delete uncalibrated image " << image_file << ": " << e.what() << std::endl;
        }

        std::cout << "Completed iteration " << (iteration + 1) << ", saved as: " << filename << std::endl;
    }

    std::cout << "\nCompleted all " << num_iterations << " iterations. Parameters saved to individual JSON files." << std::endl;

    return 0;
}