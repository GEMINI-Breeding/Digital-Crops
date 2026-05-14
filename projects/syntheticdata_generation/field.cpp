#include "field.h"
#include "main.h"
#include "Context.h"
#include "CanopyGenerator.h"
#include "utils.h"
#include "yaml-cpp/yaml.h"
#include <fstream>
#include <cstdio>
#include <iostream>

using namespace helios;


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
        float Z = 0.0f;
        if (config["crops"][i]["z"]) {
            Z = config["crops"][i]["z"].as<float>();
        }
        vec3 plant_origin = origin + make_vec3(X, Y, Z);

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

std::vector<uint> make_field(helios::Context& context, const json& params) {

    auto field = params["field"];
    json layout;
    if (field.contains("layout")) {
        layout = field["layout"];
    }
    
    json plot_shape;
    if (field.contains("plot_shape")) {
        plot_shape = field["plot_shape"];
    } else if (field.contains("layout")) {
        plot_shape = field["layout"];
    }
    
    int n_beds = getJsonNumberOr<int>(field, {"num_beds"}, 
                 getJsonNumberOr<int>(layout, {"num_beds"}, 1));
    int n_rows = getJsonNumberOr<int>(field, {"num_rows"}, 
                 getJsonNumberOr<int>(layout, {"num_rows"}, 1));
    
    std::string obj_path = getJsonStringOr(plot_shape, {"obj_file_path"}, 
                           getJsonStringOr(params, {"environment", "soil", "obj_file_path"}, "../../../obj/dirt_rocks.obj"));
    
    if (obj_path.empty()) {
        std::cerr << "Error: obj_file_path is missing in JSON parameters." << std::endl;
        return {};
    }


    // Manipulate mtl file before loading OBJ file
    std::string orig_mtl_path = obj_path.substr(0, obj_path.find_last_of("\\/")) + "/dirt_rocks.mtl.orig";

    // Replace numbers with soil color in the field
    float soil_color[3] = {0.5f, 0.4f, 0.3f}; // Default brownish color
    if (plot_shape.contains("soil_color") && plot_shape["soil_color"].is_array())
    {   
        int cnt = 0;
        for (const auto& color_val : plot_shape["soil_color"])
        {
            if (cnt >= 3) break;
            // Push to the array
            soil_color[cnt] = color_val.get<float>();
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

    std::cout << "[DEBUG] Loading OBJ from: " << obj_path << std::endl;
    std::vector<uint> UUIDs = context.loadOBJ(obj_path.c_str(), make_vec3(0,0,0), \
                    getJsonNumberOr<float>(plot_shape, {"plot_size_z"}, 0.0f), nullrotation, RGB::white);

    std::cout << "[DEBUG] loadOBJ returned " << UUIDs.size() << " primitives." << std::endl;
    if (UUIDs.empty()) {
        std::cerr << "[WARNING] loadOBJ returned no primitives for " << obj_path << std::endl;
    }

    // Rescale only X and Y to match bed dimensions, preserve Z from DEM
    // The OBJ file already has correct Z values (elevations) normalized to plant locations
    vec3 plot_extent = make_vec3(getJsonNumberOr<float>(plot_shape, {"plot_size_x"}, 1.299f), \
                    getJsonNumberOr<float>(plot_shape, {"plot_size_y"}, 3.831f), getJsonNumberOr<float>(plot_shape, {"plot_size_z"}, 0.0f));
    
    // Set margin factor to 1.00 to perfectly match exact plot dimensions without excess overlapping
    float margin_factor = 1.05f; // 
    vec3 ground_extent = make_vec3(plot_extent.x * margin_factor, plot_extent.y * margin_factor, plot_extent.z);
    
    std::cout << "[DEBUG] Rescaling to extent: (" << ground_extent.x << ", " << ground_extent.y << ", " << ground_extent.z << ")" << std::endl;
    rescaleUUIDsToSize(context, UUIDs, ground_extent);
    std::cout << "[DEBUG] Rescaling complete." << std::endl;

    // Apply plot heading rotation if specified
    float rotate_obj = getJsonNumberOr<float>(plot_shape, {"rotate_obj"}, 0.0f);
    if (rotate_obj != 0.0f) {
        // Convert degrees to radians and rotate around Z-axis
        float rotate_obj_rad = rotate_obj * M_PI / 180.0f;
        context.rotatePrimitive(UUIDs, rotate_obj_rad, "z");
        std::cout << "Rotated ground mesh by " << rotate_obj << " degrees" << std::endl;
    }

    // Compute bounding box for the original OBJ once, since it's the same for all copies
    helios::vec3 min_corner, max_corner, extent;
    getBoundingBoxAndExtent(context, UUIDs, min_corner, max_corner, extent);
    helios::vec3 bbox_center = (min_corner + max_corner) * 0.5f;

    // vec3 for center of the field. It will be calculated by averaging the x and y of all the field
    
    // Copy and paste fields
    // Total UUIDs
    vec3 center(0,0,0);
    std::vector<uint> UUIDs_total;
    for(int bed = 0;bed < n_beds;bed++){
        for(int row = 0;row<n_rows;row++){
            if (bed == 0 && row == 0) {
                // Already generated
                // Append UUIDs_copy to UUIDs_total
                UUIDs_total.insert(UUIDs_total.end(), UUIDs.begin(), UUIDs.end());
            } else {
                // Use exact plot extent for positioning to synchronize with plant grid and eliminate gaps
                float x = bed * plot_extent.x;
                float y = row * plot_extent.y;
                float z = 0;
                
                // Make a vector of x y z origin
                vec3 origin(x,y,z);
                center += origin;
                std::vector<uint> UUIDs_copy = context.copyPrimitive(UUIDs);
                
                // Translate to position at (x,y,z) centered using precomputed bbox_center
                //context.translatePrimitive(UUIDs_copy, make_vec3(x, y, z) - bbox_center);
                context.translatePrimitive(UUIDs_copy, make_vec3(x, y, z));
                
                // Append UUIDs_copy to UUIDs_total
                UUIDs_total.insert(UUIDs_total.end(), UUIDs_copy.begin(), UUIDs_copy.end());
            }
        }
    }
    center = center / (n_beds * n_rows);
    
    //return center;
    return UUIDs_total;
}