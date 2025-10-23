#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <random>
#include <sstream>
#include <algorithm>



#include "PlantArchitecture.h"
#include "Visualizer.h"
#include "RadiationModel.h"
#include "LeafOptics.h"
#include "json.hpp"
#include "CanopyGenerator.h"
#include "SyntheticAnnotation.h"
#include "SolarPosition.h"
//#include "EnergyBalanceModel.h"

#include "main.h"
#include "utils.h"
#include "field.h"
#include "yaml-cpp/yaml.h"


using namespace helios;
namespace fs = std::filesystem;

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

int main(int argc, char* argv[]){

    // Parse command-line arguments using dedicated function
    CommandLineOptions args = parseCommandLineArgs(argc, argv);

    // load parameters
    json json_params = loadParametersFromJson("../params.json");

    int num_plants = 0;
    if (json_params.contains("plot") &&
        json_params["plot"].contains("plants") &&
        json_params["plot"]["plants"].is_array()) {
      num_plants = json_params["plot"]["plants"].size();
    }
    std::cout << "Number of crops: " << num_plants << std::endl;

    // prepare output dir
    std::string output_dir;
    if (args.save_dir.size() > 0) {
      output_dir = args.save_dir;
    } else {
      output_dir = json_params.value("output_directory", "output");
    }

    if (!fs::exists(output_dir)) {
        fs::create_directories(output_dir);
    }
    std::cout << "Output directory: " << output_dir << std::endl;
    
    std::string output_name;
    if (args.output_name.size() > 0)
    {
        output_name = args.output_name;
    }else{
        output_name = "plot";
    }
    
    std::random_device rd;
    std::mt19937 rng(rd());

    // Save the original parameters once (shared across all crops)
    std::ofstream original_params_file(output_dir + "/original_params.json");
    original_params_file << std::setw(4) << json_params << std::endl;
    original_params_file.close();
    std::cout << "Saved original parameters to: original_params.json\n" << std::endl;

    // Generate individual plants
    Context context;
    LeafOptics leafoptics(&context);
    RadiationModel radiation(&context);
    
    std::vector<uint> plant_IDs;
    PlantArchitecture plantarchitecture(&context);
    for (int iteration = 0; iteration < num_plants; ++iteration) {
        std::cout << "\n=== plant " << (iteration + 1) << " of " << num_plants << " ===" << std::endl;
        
        // Create a copy of the params for this specific crop
        json sampled_params = json_params;
        
        // Select the specific crop
        if (sampled_params.contains("plot") && 
            sampled_params["plot"].contains("plants") && 
            sampled_params["plot"]["plants"].is_array() &&
            iteration < sampled_params["plot"]["plants"].size()) {
            
            // Keep only the selected crop
            json selected_crop = sampled_params["plot"]["plants"][iteration];
            sampled_params["plot"]["plants"] = json::array({selected_crop});
        }else{
            printf("[ERROR] Can't find plot definitions\n");
        }
        
        // Recursively add sampled values to all parameters with "sampling" key
        addSampledValues(sampled_params, rng);
        
        // filename with zero-padded iteration number
        std::stringstream filename_stream;
        filename_stream << output_name << "_plant_" << std::setw(4) << std::setfill('0') << iteration;
        std::string filename = filename_stream.str();
        
        // save the parameters with sampled values for this crop
        std::ofstream params_file(output_dir + "/" + filename + "_params.json");
        params_file << std::setw(4) << sampled_params << std::endl;
        params_file.close();

        // Get crop type and convert to lowercase for plant library
        std::string crop_type = sampled_params["plot"]["plants"][0]["crop_type"].get<std::string>();
        std::transform(crop_type.begin(), crop_type.end(), crop_type.begin(), ::tolower);
        
        plantarchitecture.loadPlantModelFromLibrary(crop_type);

        std::map<std::string, ShootParameters> shoot_params = plantarchitecture.getCurrentShootParameters();

        // update leaf pitch and peduncle length
        shoot_params.at("trifoliate").phytomer_parameters.leaf.pitch = sampled_params["plantarchitecture"]["phytomer_parameters"]["leaf_pitch"]["sampled"];
        shoot_params.at("trifoliate").flower_bud_break_probability = sampled_params["plantarchitecture"]["flower_bud_break_probability"]["sampled"];

        // update leaf
        shoot_params.at("trifoliate").phytomer_parameters.leaf.prototype.prototype_function = CowpeaLeafPrototype_trifoliate_OBJ;

        // apply updated parameters
        plantarchitecture.updateCurrentShootParameters("trifoliate", shoot_params.at("trifoliate"));

        // enable object data output for flower state identification
        plantarchitecture.optionalOutputObjectData("closedflowerID");
        plantarchitecture.optionalOutputObjectData("openflowerID");

        // plant count and age can be changed here
        int bed = sampled_params["plot"]["plants"][0]["bed"];
        int row = sampled_params["plot"]["plants"][0]["row"];
        vec3 origin(0, 0, 0);
        float X = sampled_params["plot"]["plants"][0]["x"];
        float Y = sampled_params["plot"]["plants"][0]["y"];
        // float Z = config["crops"][i]["Z"].as<float>();
        vec3 plant_origin = origin + make_vec3(X, Y, 0);
        uint plantID = plantarchitecture.buildPlantInstanceFromLibrary(plant_origin, 0);
        plant_IDs.push_back(plantID);
        std::cout << "Generated plant (ID:" << plantID << ")" << std::endl;

    }
    
    // Sampling for enviroment and radiation
    json sampled_env_params = sampleParametersToJson(0, json_params, rng);
    
    // Age all plants together after creation
    if (!plant_IDs.empty()) {
        float plant_age = static_cast<float>(sampled_env_params["plantarchitecture"]["initialize"]["plant_age"]["sampled"].get<float>());
        if (plant_age > 0) {
            plantarchitecture.advanceTime(plant_IDs, plant_age);
            std::cout << "Advanced all plants to age: " << plant_age << " days" << std::endl;
        }
    }

    // create ground - either OBJ-based or tile-based
    std::vector<uint> UUIDs_ground;
    if (sampled_env_params["ground"]["use_obj_ground"].get<bool>()) {
        UUIDs_ground = createObjGround(context, sampled_env_params);
        //UUIDs_ground = make_field(context, sampled_env_params);
    } else {
        // load dirt texture with fixed size (original method)
        // default: plugins/visualizer/textures/dirt.jpg
        UUIDs_ground = context.addTile(
            make_vec3(0,0,0), 
            make_vec2(sampled_env_params["ground"]["size_x"]["sampled"].get<float>(), 
                        sampled_env_params["ground"]["size_y"]["sampled"].get<float>()), 
            make_SphericalCoord(0,0), make_int2(10, 10)
        );
    }
    context.setPrimitiveData(UUIDs_ground, "twosided_flag", 0u);
   
    if (args.fast){
        Visualizer vis(1200);
        vis.clearGeometry();
        vis.buildContextGeometry(&context);
        vis.hideWatermark();
        vis.disableMessages();
        vis.setLightingModel(Visualizer::LIGHTING_PHONG);

        // Set the camera position
        float x = 0;
        float y = 0;
        float z = 1.5;
        float elevation = (90+1e-1) / 180.0 * M_PI; // To aviod flipping error because of singuarity angle
        vis.setCameraPosition(make_SphericalCoord(z, elevation, 0), make_vec3(x, y, 0));
        
        vis.plotUpdate();

        // if (args.debug){
        //     vis.plotInteractive();
        // }
        vis.plotInteractive();
    }else{
         // load color and reflectivity data
        context.loadXML( sampled_env_params["radiationmodel"]["colorboard"].get<std::string>().c_str(), true );
        context.loadXML( sampled_env_params["radiationmodel"]["leaf_surface_spectral_data"]["file"].get<std::string>().c_str(), true );
        context.loadXML( sampled_env_params["radiationmodel"]["soil_surface_spectral_data"]["file"].get<std::string>().c_str(), true );
        context.renameGlobalData("ColorReference_DGK_08", "spectrum_yellow");
        context.renameGlobalData("ColorReference_DGK_09", "spectrum_green");
        context.renameGlobalData("ColorReference_DGK_16", "spectrum_purple");
        context.renameGlobalData("ColorReference_DGK_01", "spectrum_white");

        // prepare custom flower colors
        radiation.blendSpectra("reflectivity_flower_cowpea_closed", {"spectrum_yellow", "spectrum_green"}, {0.35, 0.65});
        radiation.blendSpectra("reflectivity_flower_cowpea_open", {"spectrum_purple", "spectrum_white"}, {0.10, 0.90}); // mostly white with purple tint

        // assign colors to each object
        std::vector<uint> UUIDs_plants = plantarchitecture.getAllUUIDs();
        context.setPrimitiveData(UUIDs_plants, "reflectivity_spectrum", sampled_env_params["radiationmodel"]["leaf_surface_spectral_data"]["reflectivity"].get<std::string>());
        context.setPrimitiveData(UUIDs_plants, "transmissivity_spectrum", sampled_env_params["radiationmodel"]["leaf_surface_spectral_data"]["transmissivity"].get<std::string>());
        context.setPrimitiveData(UUIDs_ground, "reflectivity_spectrum", sampled_env_params["radiationmodel"]["soil_surface_spectral_data"]["reflectivity"].get<std::string>());

        // set specular properties for realistic shading
        context.setPrimitiveData(UUIDs_plants, "specular_exponent", 10.f);
        context.setPrimitiveData(UUIDs_ground, "specular_exponent", 10.f);

        // get unique labels for flowers and apply colors based on open/closed state
        uint flower_counter = 0;
        uint pod_counter = 0;
        
        // Initialize leaf optics properties
        LeafOpticsProperties leafopticsprops;
        leafopticsprops.chlorophyllcontent = sampled_env_params["leafoptics"]["chlorophyll_content"]["sampled"].get<int>();
        
        for (uint& id : plant_IDs) {
            std::vector<uint> IDs_flower = plantarchitecture.getPlantFlowerObjectIDs(id);
            std::vector<uint> IDs_pod = plantarchitecture.getPlantFruitObjectIDs(id);

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
                
                context.setPrimitiveData(uuids_flower, "flower", flower_counter);
                flower_counter++;
            }
            
            // Optional: pod labeling (commented out like in syntheticdata_sample_test)
            // for (uint& id_pod : IDs_pod) {
            //     std::vector<uint> uuids_pod = context.getObjectPrimitiveUUIDs(id_pod);
            //     context.setPrimitiveData(uuids_pod, "pod", pod_counter);
            //     pod_counter++;
            // }
            
            // Update leaf optical properties
            std::vector<uint> IDs_leaf = plantarchitecture.getPlantLeafObjectIDs(id);
            for (uint& id_leaf : IDs_leaf) {
                std::vector<uint> uuids_leaf = context.getObjectPrimitiveUUIDs(id_leaf);
                leafoptics.run(uuids_leaf, leafopticsprops, "cowpea_leaf");
            }
        }
        
        // add color calibration target (optional)
        CameraCalibration calibration(&context);
        calibration.addCalibriteColorboard(make_vec3(0,0.75,0.001), 0.025);

        // set up sun lighting
        SphericalCoord sun_dir = make_SphericalCoord(
            deg2rad(sampled_env_params["sun_position"]["elevation_degrees"]["sampled"].get<float>()), 
            -deg2rad(sampled_env_params["sun_position"]["azimuth_degrees"]["sampled"].get<float>())
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
        cameraproperties.focal_plane_distance = sampled_env_params["cameraproperties"]["camera_height"]["sampled"].get<float>() - sampled_env_params["cameraproperties"]["focal_plane_distance_difference"]["sampled"].get<float>(); //focus on center of scene
        cameraproperties.lens_diameter = sampled_env_params["cameraproperties"]["lens_diameter"]["sampled"].get<float>(); //make it small so it will be in focus
        cameraproperties.HFOV = sampled_env_params["cameraproperties"]["HFOV"]["sampled"].get<float>();
        cameraproperties.camera_resolution = make_int2(
            sampled_env_params["cameraproperties"]["camera_resolution_x"]["sampled"].get<int>(), 
            sampled_env_params["cameraproperties"]["camera_resolution_y"]["sampled"].get<int>()
        );
        vec3 camera_position(0, 0, 0);
        vec3 camera_lookat(0, 0, 0);

        // Calculate plant canopy center based on plant positioning
        vec3 canopy_center = make_vec3(0, 0, 0); // Plants are positioned at origin

        // Convert azimuth angle from degrees to radians
        float azimuth_rad = deg2rad(sampled_env_params["cameraproperties"]["camera_positioning"]["azimuth_angle"]["sampled"].get<float>());

        // Calculate camera position based on plant canopy center
        camera_position.x = canopy_center.x + sampled_env_params["cameraproperties"]["camera_positioning"]["distance_from_center"]["sampled"].get<float>() * cos(azimuth_rad);
        camera_position.y = canopy_center.y + sampled_env_params["cameraproperties"]["camera_positioning"]["distance_from_center"]["sampled"].get<float>() * sin(azimuth_rad);
        camera_position.z = sampled_env_params["cameraproperties"]["camera_height"]["sampled"].get<float>();

        // Calculate camera lookat point (slightly offset from canopy center)
        camera_lookat.x = canopy_center.x + sampled_env_params["cameraproperties"]["camera_positioning"]["lookat_offset_x"]["sampled"].get<float>();
        camera_lookat.y = canopy_center.y + sampled_env_params["cameraproperties"]["camera_positioning"]["lookat_offset_y"]["sampled"].get<float>();
        camera_lookat.z = canopy_center.z + sampled_env_params["cameraproperties"]["camera_positioning"]["lookat_offset_z"]["sampled"].get<float>();

        // add the camera to the radiation model
        radiation.addRadiationCamera(cameralabel, bandlabels, camera_position, camera_lookat, cameraproperties, 100);

        // set camera spectral response to simulate iPhone camera
        context.loadXML( "plugins/radiation/spectral_data/camera_spectral_library.xml", true);
        std::string camera_type = sampled_env_params["radiationmodel"]["camera_spectral_data"]["camera_type"].get<std::string>();
        radiation.setCameraSpectralResponse(cameralabel, "red", (camera_type + "_red").c_str());
        radiation.setCameraSpectralResponse(cameralabel, "green", (camera_type + "_green").c_str());
        radiation.setCameraSpectralResponse(cameralabel, "blue", (camera_type + "_blue").c_str());

        // update geometry and run radiation model
        radiation.updateGeometry();

        radiation.runBand(bandlabels);
        
        // process image using standard pipeline
        radiation.applyImageProcessingPipeline(cameralabel, "red", "green", "blue");
        
        // save rendered RGB image with custom filename
        std::string image_file = radiation.writeCameraImage(cameralabel, bandlabels, "RGB", output_dir, 0);
        std::string image_base = fs::path(image_file).stem().string();
        
        // export bounding boxes and segmentation masks in COCO format
        radiation.writeImageSegmentationMasks( cameralabel, {"flower"}, {0}, output_dir + '/' + output_name + "_labels.json", image_file );
        
        // auto-calibrate camera using colorboard reference values with quality report
        std::string corrected_image = radiation.autoCalibrateCameraImage(cameralabel, "red", "green", "blue", output_dir + '/' + output_name + ".jpeg", true);
        
        // Delete the uncalibrated image after calibrated version is created
        try {
            if (fs::exists(image_file)) {
                fs::remove(image_file);
            }
        } catch (const std::exception &e) {
            std::cout << "  Warning: Could not delete uncalibrated image " << image_file << ": " << e.what() << std::endl;
        }
    }

        
    

    std::cout << "\nCompleted all " << num_plants << " crops. Parameters saved to individual JSON files." << std::endl;

    return 0;
}