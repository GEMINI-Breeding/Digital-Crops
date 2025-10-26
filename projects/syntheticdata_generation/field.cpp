#include "field.h"
#include "main.h"
#include "Context.h"
#include "CanopyGenerator.h"
#include "yaml-cpp/yaml.h"
#include <fstream>
#include <cstdio>
#include <iostream>

using namespace helios;

// std::vector<uint> make_field(Context &context, std::string obj_path, YAML::Node config){

//     int n_beds = config["n_beds"].as<int>(); 
//     int n_rows = config["n_rows"].as<int>(); 

//     // Manipulate mtl file before loading OBJ file
//     std::string orig_mtl_path = obj_path.substr(0, obj_path.find_last_of("\\/")) + "/dirt_rocks.mtl.orig";

//     // Replace numbers with soil color in the config
//     float soil_color[3];
//     if (config["soil_color"])
//     {   int cnt = 0;
//         for (YAML::const_iterator it = config["soil_color"].begin(); it != config["soil_color"].end(); ++it)
//         {
//             // Push to the array
//             soil_color[cnt] = it->as<float>();
//             cnt++;
//         }
        
//         // Rewrite the mtl file
//         // Remove the mtl file if it exists
//         std::string new_mtl_path = obj_path.substr(0, obj_path.find_last_of("\\/")) + "/dirt_rocks.mtl";
//         std::remove(new_mtl_path.c_str());
        
//         std::ofstream file(new_mtl_path);
//         file << "# Blender MTL File: 'None'\n";
//         file << "# Material Count: 1\n\n";
//         file << "newmtl None\n";
//         file << "Ns 500.000001\n";
//         file << "Ka " << soil_color[0] << " " << soil_color[1] << " " << soil_color[2] << "\n";
//         file << "Kd " << soil_color[0]*0.8 << " " << soil_color[1]*0.8 << " " << soil_color[2]*0.8 << "\n";
//         file << "Ks " << soil_color[0]*0.8 << " " << soil_color[1]*0.8 << " " << soil_color[2]*0.8 << "\n";
//         file << "Ke 0.000000 0.000000 0.000000\n";
//         file << "Ni 1.450000\n";
//         file << "d 1.000000\n";
//         file << "illum 2\n";

//         file.close();
//     }

//     std::vector<uint> UUIDs = context.loadOBJ(obj_path.c_str(), make_vec3(0,0,0), BED_HEIGHT, nullrotation, RGB::white);
//     // vec3 for center of the field. It will be calculated by averaging the x and y of all the field
//     vec3 center(0,0,0);
//     // Total UUIDs
//     std::vector<uint> UUIDs_total;
//     for(int bed = 0;bed < n_beds;bed++){
//         for(int row=0;row<n_rows;row++){
//             float x = bed * BED_WIDTH;
//             float y = row * BED_LENGTH;
//             float z = 0;

//             // Make a vector of x y z origin
//             vec3 origin(x,y,z);
//             center += origin;
//             std::vector<uint> UUIDs_copy = context.copyPrimitive(UUIDs);
//             //context.translatePrimitive(UUIDs_copy, make_vec3(x,y,z));

//             // Append UUIDs_copy to UUIDs_total
//             UUIDs_total.insert(UUIDs_total.end(), UUIDs_copy.begin(), UUIDs_copy.end());
//         }
//     }
//     center = center / (n_beds * n_rows);
//     //return center;
//     return UUIDs_total;
// }

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

    auto config = params["plot"];
    int n_beds = config["n_beds"].get<int>(); 
    int n_rows = config["n_rows"].get<int>(); 
    
    std::string obj_path = params["ground"]["obj_file_path"].get<std::string>();

    // Manipulate mtl file before loading OBJ file
    std::string orig_mtl_path = obj_path.substr(0, obj_path.find_last_of("\\/")) + "/dirt_rocks.mtl.orig";

    // Replace numbers with soil color in the config
    float soil_color[3];
    if (config.contains("soil_color") && config["soil_color"].is_array())
    {   
        int cnt = 0;
        for (const auto& color_val : config["soil_color"])
        {
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

    std::vector<uint> UUIDs = context.loadOBJ(obj_path.c_str(), make_vec3(0,0,0), config["bed_height"], nullrotation, RGB::white);
    // vec3 for center of the field. It will be calculated by averaging the x and y of all the field
    vec3 center(0,0,0);
    // Total UUIDs
    std::vector<uint> UUIDs_total;
    for(int bed = 0;bed < n_beds;bed++){
        for(int row=0;row<n_rows;row++){
            float x = bed * config["bed_width"].get<float>();
            float y = row * config["bed_length"].get<float>();
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