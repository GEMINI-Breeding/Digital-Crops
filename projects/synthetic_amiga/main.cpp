#include <cstdlib>
#include "Visualizer.h"
#include "CanopyGenerator.h"
#include "SyntheticAnnotation.h"
//#include "RadiationModel.h"
#include "SolarPosition.h"
//#include "EnergyBalanceModel.h"

#include "main.h"
#include "utils.h"
#include "yaml-cpp/yaml.h"

using namespace helios;

#include "PlantArchitecture.h"
#include "Visualizer.h"
#include "RadiationModel.h"
#include "json.hpp"
#include "main.h"

#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <random>
#include <sstream>

using namespace helios;
namespace fs = std::filesystem;



//vec3 make_field(Context &context, std::string obj_path, YAML::Node config){
std::vector<uint> make_field(Context &context, std::string obj_path, YAML::Node config){

    int n_beds = config["n_beds"].as<int>(); 
    int n_rows = config["n_rows"].as<int>(); 

    // Manipulate mtl file before loading OBJ file
    std::string orig_mtl_path = obj_path.substr(0, obj_path.find_last_of("\\/")) + "/dirt_rocks.mtl.orig";

    // Replace numbers with soil color in the config
    float soil_color[3];
    if (config["soil_color"])
    {   int cnt = 0;
        for (YAML::const_iterator it = config["soil_color"].begin(); it != config["soil_color"].end(); ++it)
        {
            // Push to the array
            soil_color[cnt] = it->as<float>();
            cnt++;
        }
        
        // Rewrite the mtl file
        // Remove the mtl file if it exists
        std::string new_mtl_path = obj_path.substr(0, obj_path.find_last_of("\\/")) + "/dirt_rocks.mtl";
        std::remove(new_mtl_path.c_str());
        
        std::ofstream file(new_mtl_path);
        file << "# Blender MTL File: 'None'\n";
        file << "# Material Count: 1\n\n";
        file << "newmtl None\n";
        file << "Ns 500.000001\n";
        file << "Ka " << soil_color[0] << " " << soil_color[1] << " " << soil_color[2] << "\n";
        file << "Kd " << soil_color[0]*0.8 << " " << soil_color[1]*0.8 << " " << soil_color[2]*0.8 << "\n";
        file << "Ks " << soil_color[0]*0.8 << " " << soil_color[1]*0.8 << " " << soil_color[2]*0.8 << "\n";
        file << "Ke 0.000000 0.000000 0.000000\n";
        file << "Ni 1.450000\n";
        file << "d 1.000000\n";
        file << "illum 2\n";

        file.close();
    }

    std::vector<uint> UUIDs = context.loadOBJ(obj_path.c_str(), make_vec3(0,0,0), BED_HEIGHT, nullrotation, RGB::white);
    // vec3 for center of the field. It will be calculated by averaging the x and y of all the field
    vec3 center(0,0,0);
    // Total UUIDs
    std::vector<uint> UUIDs_total;
    for(int bed = 0;bed < n_beds;bed++){
        for(int row=0;row<n_rows;row++){
            float x = bed * BED_WIDTH;
            float y = row * BED_LENGTH;
            float z = 0;

            // Make a vector of x y z origin
            vec3 origin(x,y,z);
            center += origin;
            std::vector<uint> UUIDs_copy = context.copyPrimitive(UUIDs);
            //context.translatePrimitive(UUIDs_copy, make_vec3(x,y,z));

            // Append UUIDs_copy to UUIDs_total
            UUIDs_total.insert(UUIDs_total.end(), UUIDs_copy.begin(), UUIDs_copy.end());
        }
    }
    center = center / (n_beds * n_rows);
    //return center;
    return UUIDs_total;
}


std::vector<uint> plant_crops(CanopyGenerator &canopygenerator, Context &context, YAML::Node config){
    // Canopy generator model
    //CanopyGenerator canopygenerator(&context);
    // Plant Sorghum based on the config locations
    int n_crops = config["crops"].size();
    std::vector<uint> UUIDs_total;
    uint plant_id = 0;
    // Set random seed
    canopygenerator.seedRandomGenerator(100);


    for (int i = 0; i < config["crops"].size(); i++){
        int bed = config["crops"][i]["bed"].as<int>();
        int row = config["crops"][i]["row"].as<int>();
        vec3 origin(0, 0, 0);
        float X = config["crops"][i]["x"].as<float>();
        float Y = config["crops"][i]["y"].as<float>();
        // float Z = config["crops"][i]["Z"].as<float>();
        vec3 plant_origin = origin + make_vec3(X, Y, 0);

        //printf(config["crops"][i]["crop_type"].as<std::string>().c_str());
        // std::cout << config["crops"][i]["crop_type"] << std::endl;
        if (config["crops"][i]["crop_type"].as<std::string>() == "Sorghum"){
            SorghumCanopyParameters parameters;
            parameters.canopy_origin = plant_origin;
            parameters.sorghum_stage = config["crops"][i]["growth_stage"].as<int>();
            plant_id = canopygenerator.sorghum(parameters, plant_origin); // Gererate a single Sorhgum plant


        }else if (config["crops"][i]["crop_type"].as<std::string>() == "Cowpea"){
            BeanParameters parameters;
            parameters.canopy_origin = plant_origin;
            // Read crop color from the config
            float crop_color[3];
            if(config["crops"][i]["plant_color"]){
                int cnt = 0;
                for (YAML::const_iterator it = config["crops"][i]["plant_color"].begin(); it != config["crops"][i]["plant_color"].end(); ++it)
                {
                    // Push to the array
                    crop_color[cnt] = it->as<float>();
                    cnt++;
                }
               parameters.shoot_color = make_RGBcolor(crop_color[0], crop_color[1], crop_color[2]);
               //parameters.shoot_color = make_RGBcolor(1,0,0);
            }
            plant_id = canopygenerator.bean(parameters, plant_origin); // Gererate a single Sorhgum plant
        }else{

            std::cout << "Crop type not supported" << std::endl;
            continue;
        }

        std::vector<uint> UUIDs_copy = canopygenerator.getAllUUIDs(plant_id);
        UUIDs_total.insert(UUIDs_total.end(), UUIDs_copy.begin(), UUIDs_copy.end());
    }

    return UUIDs_total;
}


// int main(){
//     Context context;

//     // Get the path of main.cpp
//     std::string path = __FILE__;
//     path = path.substr(0, path.find_last_of("\\/"));
//     // Print path
//     std::cout << path << std::endl;
//     // Object file path
//     std::string obj_path = path + "/../../obj/dirt_rocks.obj";
//     std::cout << obj_path << std::endl;

//     // Read yaml file
//     //std::string yaml_path = path + "/python_scripts/config.yaml";
//     std::string yaml_path = path + "/../../data/2023-06-20-P4-RGB_Plot_276.yaml";
//     std::cout << yaml_path << std::endl;
//     YAML::Node config = load_yaml(yaml_path);

//     // OBJ 3D Model
//     std::vector<uint> UUIDs_ground = make_field(context, obj_path, config);

//     // Plant sorghum
//     CanopyGenerator canopygenerator(&context);

//     std::vector<uint> UUIDs_leaves = plant_crops(canopygenerator, context, config);
//     std::vector<uint> UUIDs_all = context.getAllUUIDs();

//     Visualizer visualizer(1920);
//     visualizer.hideWatermark();
//     visualizer.buildContextGeometry(&context);
//     visualizer.setLightingModel(Visualizer::LIGHTING_PHONG_SHADOWED);
//     visualizer.setCameraPosition(SphericalCoord(5, 0.5*float(M_PI), 0), make_vec3(0, 0, 0));

// #if 1
//     visualizer.plotInteractive();
// #else
//     visualizer.plotUpdate( true );
//     wait(5);
// #endif

//     // Save the image to the file.
//     std::string this_view_path =  std::string("../data");
//     std::system(("mkdir -p " + this_view_path).c_str());
//     // Generate the image name from yaml_path
//     std::string image_view_path = this_view_path + "/" + yaml_path.substr(yaml_path.find_last_of("/")+1) + ".jpg";
//     // std::string image_view_path = this_view_path + "/" "RGB_rendering.jpeg";
//     visualizer.printWindow(image_view_path.c_str());

  
// #if 0
//     // Generate annotations
//     // Declare the Synthetic Annotation class.
//     SyntheticAnnotation annotation(&context);
//     //annotation.setCameraPosition(field_origin + make_vec3(0, 0, 10), field_origin);
//     //annotation.setCameraPosition(make_vec3(0, 0, 1), make_vec3(1, 0, 1));
//     annotation.setCameraPosition(make_vec3(0, 0, 5), make_vec3(1, 0, 0)); // 왜 이렇게 해야하는지 잘 모르겠음
//     annotation.disableInstanceSegmentation();
//     //annotation.setWindowSize(800, 800);

//     // Add labels according to whatever scheme we want.
//     for (int p = 0; p < canopygenerator.getPlantCount(); p++)
//     {   
//         // loop over plants
//         //if (!config.simulation_type.empty() && config.simulation_type[0] == "rgb")
//         {
//             annotation.labelPrimitives(canopygenerator.getTrunkUUIDs(p), "trunks");
//             annotation.labelPrimitives(canopygenerator.getBranchUUIDs(p), "branches");
//             annotation.labelPrimitives(canopygenerator.getLeafUUIDs(p), "leaves");
//             std::vector<std::vector<std::vector<uint>>> fruitUUIDs = canopygenerator.getFruitUUIDs(p);
//             if (fruitUUIDs.size() == 1)
//             { // no clusters, only individual fruit
//                 for (auto &fruit : fruitUUIDs.front())
//                     annotation.labelPrimitives(fruit, "clusters");
//             }
//             else if (fruitUUIDs.size() > 1)
//             { // fruit contained within cluster - label by cluster
//                 for (auto &cluster : fruitUUIDs)
//                     annotation.labelPrimitives(flatten(cluster), "clusters");
//             }
//         }
//     }
//     // Render the annotations.
//     std::string this_image_dir =  std::string("rendered_images/annotations");
//     std::cout << this_image_dir;
//     annotation.render(this_image_dir.c_str());
// #endif

//     return 0;
// }


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

// Function to create OBJ-based ground
std::vector<helios::uint> createObjGround(helios::Context& context, const json& params) {
    if (!params["ground"]["use_obj_ground"].get<bool>()) {
        return {};
    }
    
    // Load the OBJ file
    std::vector<helios::uint> UUIDs = context.loadOBJ(
        params["ground"]["obj_file_path"].get<std::string>().c_str(), 
        make_vec3(0, 0, 0), 
        params["ground"]["ground_scale"]["sampled"].get<float>(), 
        nullrotation, 
        RGB::white
    );
    
    return UUIDs;
}

int main(){

    // load parameters
    json json_params = loadParametersFromJson("../params.json");

   
    int num_crops = 0;
    if (json_params.contains("plants") && 
        json_params["plants"].contains("crops") && 
        json_params["plants"]["crops"].is_array()) {
        num_crops = json_params["plants"]["crops"].size();
    }

    std::cout << "Number of crops: " << num_crops << std::endl;

    // prepare output dir
    std::string output_dir = json_params.value("output_directory", "output");
    if (!fs::exists(output_dir)) {
        fs::create_directories(output_dir);
    }
    std::cout << "Output directory: " << output_dir << std::endl;

    std::random_device rd;
    std::mt19937 rng(rd());

    // Save the original parameters once (shared across all crops)
    std::ofstream original_params_file(output_dir + "/original_params.json");
    original_params_file << std::setw(4) << json_params << std::endl;
    original_params_file.close();
    std::cout << "Saved original parameters to: original_params.json\n" << std::endl;

    Context context;
    PlantArchitecture plantarchitecture(&context);
    for (int iteration = 0; iteration < num_crops; ++iteration) {
        std::cout << "\n=== Crop " << (iteration + 1) << " of " << num_crops << " ===" << std::endl;


        // sample parameters - adds "sampled" values to the structure
        json params = sampleParametersToJson(iteration, json_params, rng);

        // filename with zero-padded iteration number
        std::stringstream filename_stream;
        filename_stream << "crop_" << std::setw(4) << std::setfill('0') << iteration;
        std::string filename = filename_stream.str();
        
        // save the parameters with sampled values for this crop
        std::ofstream params_file(output_dir + "/" + filename + "_params.json");
        params_file << std::setw(4) << params << std::endl;
        params_file.close();

        plantarchitecture.loadPlantModelFromLibrary(params["plants"]["crops"][0]["crop_type"]);

        std::map<std::string, ShootParameters> shoot_params = plantarchitecture.getCurrentShootParameters();

        // update leaf pitch and peduncle length
        shoot_params.at("trifoliate").phytomer_parameters.leaf.pitch = params["plantarchitecture"]["phytomer_parameters"]["leaf_pitch"]["sampled"];
        shoot_params.at("trifoliate").flower_bud_break_probability = params["plantarchitecture"]["flower_bud_break_probability"]["sampled"];

        // update leaf
        shoot_params.at("trifoliate").phytomer_parameters.leaf.prototype.prototype_function = CowpeaLeafPrototype_trifoliate_OBJ;

        // apply updated parameters
        plantarchitecture.updateCurrentShootParameters("trifoliate", shoot_params.at("trifoliate"));

        // enable object data output for flower state identification
        plantarchitecture.optionalOutputObjectData("closedflowerID");
        plantarchitecture.optionalOutputObjectData("openflowerID");

        // plant count and age can be changed here
        std::vector<uint> plant_IDs = plantarchitecture.buildPlantCanopyFromLibrary(
            make_vec3(0, 0, 0), 
            make_vec2(params["plantarchitecture"]["initialize"]["plant_spacing_x"]["sampled"], 
                     params["plantarchitecture"]["initialize"]["plant_spacing_y"]["sampled"]),
            make_int2(params["plantarchitecture"]["initialize"]["num_columns"]["sampled"], 
                     params["plantarchitecture"]["initialize"]["plant_count"]["sampled"]), 
            static_cast<int>(params["plantarchitecture"]["initialize"]["plant_age"]["sampled"].get<float>())
        );
        std::vector<uint> UUIDs_plants = plantarchitecture.getAllUUIDs();

        // create ground - either OBJ-based or tile-based
        std::vector<uint> UUIDs_ground;
        if (params["ground"]["use_obj_ground"].get<bool>()) {
            UUIDs_ground = createObjGround(context, params);
        } else {
            // load dirt texture with fixed size (original method)
            // default: plugins/visualizer/textures/dirt.jpg
            UUIDs_ground = context.addTile(
                make_vec3(0,0,0), 
                make_vec2(params["ground"]["size_x"]["sampled"].get<float>(), 
                         params["ground"]["size_y"]["sampled"].get<float>()), 
                make_SphericalCoord(0,0), make_int2(10, 10)
            );
        }
        context.setPrimitiveData(UUIDs_ground, "twosided_flag", 0u);

        // load color and reflectivity data
        context.loadXML( params["radiationmodel"]["colorboard"].get<std::string>().c_str(), true );
        context.loadXML( params["radiationmodel"]["leaf_surface_spectral_data"]["file"].get<std::string>().c_str(), true );
        context.loadXML( params["radiationmodel"]["soil_surface_spectral_data"]["file"].get<std::string>().c_str(), true );
        context.renameGlobalData("ColorReference_DGK_08", "spectrum_yellow");
        context.renameGlobalData("ColorReference_DGK_09", "spectrum_green");
        context.renameGlobalData("ColorReference_DGK_16", "spectrum_purple"); // purple/mauve for open flowers

        // assign colors to each object
        context.setPrimitiveData(UUIDs_plants, "reflectivity_spectrum", params["radiationmodel"]["leaf_surface_spectral_data"]["reflectivity"].get<std::string>());
        context.setPrimitiveData(UUIDs_plants, "transmissivity_spectrum", params["radiationmodel"]["leaf_surface_spectral_data"]["transmissivity"].get<std::string>());
        context.setPrimitiveData(UUIDs_ground, "reflectivity_spectrum", params["radiationmodel"]["soil_surface_spectral_data"]["reflectivity"].get<std::string>());

        // set specular properties for realistic shading
        context.setPrimitiveData(UUIDs_plants, "specular_exponent", 10.f);
        context.setPrimitiveData(UUIDs_ground, "specular_exponent", 10.f);

        // prepare custom flower colors
        RadiationModel radiation(&context);
        radiation.blendSpectra("reflectivity_flower_cowpea_closed", {"spectrum_yellow", "spectrum_green"}, {0.35, 0.65});
        radiation.blendSpectra("reflectivity_flower_cowpea_open", {"spectrum_purple", "spectrum_green"}, {0.7, 0.3});

        // get unique labels for flowers and apply colors based on open/closed state
        uint counter = 0;
        for (uint& id : plant_IDs) {
            std::vector<uint> IDs_flower = plantarchitecture.getPlantFlowerObjectIDs(id);

            for (uint& id_flower : IDs_flower) {
                std::vector<uint> uuids_flower = context.getObjectPrimitiveUUIDs(id_flower);
                
                // check if flower is open or closed based on object data
                bool is_closed_flower = false;
                bool is_open_flower = false;
                
                if (context.doesObjectDataExist(id_flower, "closedflowerID")) {
                    is_closed_flower = true;
                }
                else if (context.doesObjectDataExist(id_flower, "openflowerID")) {
                    is_open_flower = true;
                }
                
                if (is_closed_flower) {
                    context.setPrimitiveData(uuids_flower, "reflectivity_spectrum", "reflectivity_flower_cowpea_closed");
                } else if (is_open_flower) {
                    context.setPrimitiveData(uuids_flower, "reflectivity_spectrum", "reflectivity_flower_cowpea_open");
                } else {
                    context.setPrimitiveData(uuids_flower, "reflectivity_spectrum", "reflectivity_flower_cowpea_closed");
                }
                
                context.setPrimitiveData(uuids_flower, "flower", counter);
                counter++;
            }
        }

        // add color calibration target (optional)
        CameraCalibration calibration(&context);
        calibration.addCalibriteColorboard(make_vec3(0,0.75,0.001), 0.025);

        // set up sun lighting
        SphericalCoord sun_dir = make_SphericalCoord(
            deg2rad(params["sun_position"]["elevation_degrees"]["sampled"].get<float>()), 
            -deg2rad(params["sun_position"]["azimuth_degrees"]["sampled"].get<float>())
        );
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
        radiation.setDiffuseSpectrum( bandlabels, "solar_spectrum_diffuse_ASTMG173");

        std::string cameralabel = "camera";

        // camera params
        CameraProperties cameraproperties;
        cameraproperties.focal_plane_distance = params["cameraproperties"]["camera_height"]["sampled"].get<float>() - params["cameraproperties"]["focal_plane_distance_difference"]["sampled"].get<float>(); //focus on center of scene
        cameraproperties.lens_diameter = params["cameraproperties"]["lens_diameter"]["sampled"].get<float>(); //make it small so it will be in focus
        cameraproperties.HFOV = params["cameraproperties"]["HFOV"]["sampled"].get<float>();
        cameraproperties.camera_resolution = make_int2(
            params["cameraproperties"]["camera_resolution_x"]["sampled"].get<int>(), 
            params["cameraproperties"]["camera_resolution_y"]["sampled"].get<int>()
        );
        vec3 camera_position(0, 0, 0);
        vec3 camera_lookat(0, 0, 0);

        // Calculate plant canopy center based on plant positioning
        vec3 canopy_center = make_vec3(0, 0, 0); // Plants are positioned at origin

        // Convert azimuth angle from degrees to radians
        float azimuth_rad = deg2rad(params["cameraproperties"]["camera_positioning"]["azimuth_angle"]["sampled"].get<float>());

        // Calculate camera position based on plant canopy center
        camera_position.x = canopy_center.x + params["cameraproperties"]["camera_positioning"]["distance_from_center"]["sampled"].get<float>() * cos(azimuth_rad);
        camera_position.y = canopy_center.y + params["cameraproperties"]["camera_positioning"]["distance_from_center"]["sampled"].get<float>() * sin(azimuth_rad);
        camera_position.z = params["cameraproperties"]["camera_height"]["sampled"].get<float>();

        // Calculate camera lookat point (slightly offset from canopy center)
        camera_lookat.x = canopy_center.x + params["cameraproperties"]["camera_positioning"]["lookat_offset_x"]["sampled"].get<float>();
        camera_lookat.y = canopy_center.y + params["cameraproperties"]["camera_positioning"]["lookat_offset_y"]["sampled"].get<float>();
        camera_lookat.z = canopy_center.z + params["cameraproperties"]["camera_positioning"]["lookat_offset_z"]["sampled"].get<float>();

        // add the camera to the radiation model
        radiation.addRadiationCamera(cameralabel, bandlabels, camera_position, camera_lookat, cameraproperties, 100);

        // set camera spectral response to simulate iPhone camera
        context.loadXML( "plugins/radiation/spectral_data/camera_spectral_library.xml", true);
        std::string camera_type = params["radiationmodel"]["camera_spectral_data"]["camera_type"].get<std::string>();
        radiation.setCameraSpectralResponse(cameralabel, "red", (camera_type + "_red").c_str());
        radiation.setCameraSpectralResponse(cameralabel, "green", (camera_type + "_green").c_str());
        radiation.setCameraSpectralResponse(cameralabel, "blue", (camera_type + "_blue").c_str());

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

    std::cout << "\nCompleted all " << num_crops << " crops. Parameters saved to individual JSON files." << std::endl;

    return 0;
}