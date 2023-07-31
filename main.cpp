#include "Visualizer.h"
#include "CanopyGenerator.h"

#include "main.h"
#include "yaml-cpp/yaml.h"

using namespace helios;

YAML::Node load_yaml(std::string yaml_path){
    YAML::Node config = YAML::LoadFile(yaml_path);

    // Print all the nodes
    std::cout << "All nodes: " << config << "\n";

    // Field config
    std::cout << "Field config: " << "\n";
    std::cout << "n_beds: " << config["n_beds"] << "\n";
    std::cout << "n_rows: " << config["n_rows"] << "\n";
    // std::cout << "bed_width: " << config["bed_width"] << "\n";
    // std::cout << "bed_length: " << config["bed_length"] << "\n";
    // std::cout << "bed_height: " << config["bed_height"] << "\n";


    if (config["crops"]){
        // Print all crops using for loop
        std::cout << "Crops: " << "\n";

        // Get the length of crops
        int n_crops = config["crops"].size();
        std::cout << "Number of crops: " << n_crops << "\n";


    }

    
    return config;
}

int make_field(Context &context, std::string obj_path, YAML::Node config){

    int n_beds = config["n_beds"].as<int>(); //6
    int n_rows = config["n_rows"].as<int>(); // 20

    std::vector<uint> UUIDs = context.loadOBJ(obj_path.c_str(), make_vec3(0,0,0), BED_HEIGHT, nullrotation, RGB::white);

    for(int bed = 0;bed < n_beds;bed++){
        for(int row=0;row<n_rows;row++){
            float x = bed * BED_WIDTH;
            float y = row * BED_LENGTH;
            float z = 0;
            std::vector<uint> UUIDs_copy = context.copyPrimitive(UUIDs);
            context.translatePrimitive(UUIDs_copy, make_vec3(x,y,z));
        }
    }
}

int plant_sorghum(Context &context, YAML::Node config){
    // Canopy generator model
    CanopyGenerator canopygenerator(&context);

    //Declare the parameter set for VSP grapevine
    SorghumCanopyParameters parameters;
    parameters.plant_count = make_int2(2,8);


    //Variable defining the location of the plant
//    vec3 origin(0,0,0);
    //Add the sorghum geometry to the Context
//    canopygenerator.sorghum( parameters, origin );

    int n_beds = 2; //6
    int n_rows = 2; // 20

    // Plant Sorghum based on the config locations
    int n_crops = config["crops"].size();
    for (int i = 0; i < config["crops"].size(); i++){
        int bed = config["crops"][i]["bed"].as<int>();
        int row = config["crops"][i]["row"].as<int>();

        // float x = bed * BED_WIDTH;
        // float y = row * BED_LENGTH;
        // float z = 0;
        vec3 origin(-BED_WIDTH/2,-BED_LENGTH/2,0);

        float X = config["crops"][i]["X"].as<float>() / 281 * 2 * BED_WIDTH;
        float Y = config["crops"][i]["Y"].as<float>() / 376 * BED_LENGTH;
        // float Z = config["crops"][i]["Z"].as<float>();
        vec3 plant_origin = origin + make_vec3(X, Y, 0);
        parameters.canopy_origin = plant_origin;
        canopygenerator.sorghum( parameters, plant_origin ); // Gererate a single Sorhgum plant
    }



    return 0;
}

int main(){
    Context context;


    // Get the path of main.cpp
    std::string path = __FILE__;
    path = path.substr(0, path.find_last_of("\\/"));
    // Print path
    std::cout << path << std::endl;
    // Object file path
    std::string obj_path = path + "/obj/dirt_rocks.obj";
    std::cout << obj_path << std::endl;

    // Read yaml file
    std::string yaml_path = path + "/python_scripts/data.yaml";
    std::cout << yaml_path << std::endl;
    YAML::Node config = load_yaml(yaml_path);

    // OBJ 3D Model
    make_field(context, obj_path, config);

    // Plant sorghum
    plant_sorghum(context, config);

    // Set Visualizer
    Visualizer visualizer(800);
    visualizer.buildContextGeometry(&context);
    // Set the lighting model
    visualizer.setLightingModel(Visualizer::LIGHTING_PHONG_SHADOWED);

    visualizer.plotInteractive();

    return 0;
}
