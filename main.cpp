#include "Visualizer.h"
#include "CanopyGenerator.h"
#include "SyntheticAnnotation.h"
#include "RadiationModel.h"
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

//vec3 make_field(Context &context, std::string obj_path, YAML::Node config){
std::vector<uint> make_field(Context &context, std::string obj_path, YAML::Node config){

    int n_beds = config["n_beds"].as<int>(); //6
    int n_rows = config["n_rows"].as<int>(); // 20

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
            context.translatePrimitive(UUIDs_copy, make_vec3(x,y,z));

            // Append UUIDs_copy to UUIDs_total
            UUIDs_total.insert(UUIDs_total.end(), UUIDs_copy.begin(), UUIDs_copy.end());
        }
    }
    center = center / (n_beds * n_rows);
    //return center;
    return UUIDs_total;
}

std::vector<uint> plant_sorghum(Context &context, YAML::Node config){
    // Canopy generator model
    //CanopyGenerator canopygenerator(&context);

    //Declare the parameter set for VSP grapevine
    SorghumCanopyParameters parameters;
#if 0
    //Set the parameters
    parameters.plant_count = make_int2(2,8);
    int n_beds = config["n_beds"].as<int>(); //6
    int n_rows = config["n_rows"].as<int>();// 20
    for (int i = 0;i < n_beds;++i){
        for (int j = 0;j < n_rows;++j){
            #if 0
            //Variable defining the location of the plant
            vec3 origin(i * BED_WIDTH, j * BED_LENGTH, 0);
            //Add the sorghum geometry to the Context
            canopygenerator.sorghum(parameters, origin );
            #else
            //Variable defining the location of the plant
            parameters.canopy_origin = make_vec3(i * BED_WIDTH, j * BED_LENGTH, 0);
            //Add the sorghum geometry to the Context
            canopygenerator.buildCanopy(parameters);
            #endif
        }
    }
#else
    // Plant Sorghum based on the config locations
    int n_crops = config["crops"].size();
    std::vector<uint> UUIDs_total;
    for (int i = 0; i < config["crops"].size(); i++){
        int bed = config["crops"][i]["bed"].as<int>();
        int row = config["crops"][i]["row"].as<int>();

        // float x = bed * BED_WIDTH;
        // float y = row * BED_LENGTH;
        // float z = 0;
        vec3 origin(-BED_WIDTH/2,-BED_LENGTH/2,0);

        float X = (281-config["crops"][i]["x"].as<float>()) / 281 * 2 * BED_WIDTH;
        float Y = config["crops"][i]["y"].as<float>() / 376 * BED_LENGTH;
        // float Z = config["crops"][i]["Z"].as<float>();
        vec3 plant_origin = origin + make_vec3(X, Y, 0);
        parameters.canopy_origin = plant_origin;
        parameters.sorghum_stage = config["crops"][i]["growth_stage"].as<int>();
        uint plant_id = canopygenerator.sorghum( parameters, plant_origin ); // Gererate a single Sorhgum plant       
        std::vector<uint> UUIDs_copy = canopygenerator.getAllUUIDs(plant_id);
        UUIDs_total.insert(UUIDs_total.end(), UUIDs_copy.begin(), UUIDs_copy.end());
    }
#endif
    return UUIDs_total;
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
    std::string yaml_path = path + "/python_scripts/config.yaml";
    std::cout << yaml_path << std::endl;
    YAML::Node config = load_yaml(yaml_path);

    // OBJ 3D Model
    std::vector<uint> UUIDs_ground = make_field(context, obj_path, config);

    // Plant sorghum
    std::vector<uint> UUIDs_plant = plant_sorghum(context, config);

    // Get all UUIDs
    std::vector<uint> UUIDs_total;
    for( uint UUID : UUIDs_total ){
        std::vector<vec3> vertices = context.getPrimitiveVertices(UUID);
        vec3 vertex = vertices.at(0);
        float z = vertex.z;
        context.setPrimitiveData(UUID,"height",z);
    }


    RadiationModel radiation(&context);
    uint sourceID = radiation.addCollimatedRadiationSource(make_SphericalCoord(0.4* M_PI, 0.25 * M_PI));
    radiation.addRadiationBand("SW");
    radiation.disableEmission("SW");
    radiation.setDiffuseRadiationFlux("SW", 0.f);
    radiation.setSourceFlux(sourceID, "SW", 500);
    radiation.setScatteringDepth("SW", 0); //you must set this >0 if you have nonzero reflectivity or transmissivity
    radiation.addRadiationBand("LW");
    radiation.setDiffuseRadiationFlux("LW", 350);
    radiation.setScatteringDepth("LW", 0); //you must set this >0 if you have emissivity < 1
    context.setPrimitiveData(UUIDs_plant, "temperature", 280.f);
    context.setPrimitiveData(UUIDs_ground, "twosided_flag", uint(0));
    radiation.updateGeometry();
    radiation.runBand("SW");
    //radiation.runBand("LW");

    // Set Visualizer
    Visualizer visualizer(800);
    visualizer.hideWatermark();
    
    visualizer.buildContextGeometry(&context);
    // Set the lighting model
    visualizer.setLightingModel(Visualizer::LIGHTING_PHONG_SHADOWED);

#if 1
    visualizer.setColorbarFontColor(RGB::gray);
    visualizer.colorContextPrimitivesByData("radiation_flux_SW");
#endif

    visualizer.plotInteractive();

    // Save the image to the file.
    std::string this_view_path =  std::string("rendered_images");
    std::system(("mkdir -p " + this_view_path).c_str());
    std::string image_view_path = this_view_path + "/" "RGB_rendering.jpeg";
    visualizer.printWindow(image_view_path.c_str());

  
#if 0
    // Generate annotations
    // Declare the Synthetic Annotation class.
    SyntheticAnnotation annotation(&context);
    //annotation.setCameraPosition(field_origin + make_vec3(0, 0, 10), field_origin);
    //annotation.setCameraPosition(make_vec3(0, 0, 1), make_vec3(1, 0, 1));
    annotation.setCameraPosition(make_vec3(0, 0, 5), make_vec3(1, 0, 0)); // 왜 이렇게 해야하는지 잘 모르겠음
    annotation.disableInstanceSegmentation();
    //annotation.setWindowSize(800, 800);

    // Add labels according to whatever scheme we want.
    for (int p = 0; p < canopygenerator.getPlantCount(); p++)
    {   
        // loop over plants
        //if (!config.simulation_type.empty() && config.simulation_type[0] == "rgb")
        {
            annotation.labelPrimitives(canopygenerator.getTrunkUUIDs(p), "trunks");
            annotation.labelPrimitives(canopygenerator.getBranchUUIDs(p), "branches");
            annotation.labelPrimitives(canopygenerator.getLeafUUIDs(p), "leaves");
            std::vector<std::vector<std::vector<uint>>> fruitUUIDs = canopygenerator.getFruitUUIDs(p);
            if (fruitUUIDs.size() == 1)
            { // no clusters, only individual fruit
                for (auto &fruit : fruitUUIDs.front())
                    annotation.labelPrimitives(fruit, "clusters");
            }
            else if (fruitUUIDs.size() > 1)
            { // fruit contained within cluster - label by cluster
                for (auto &cluster : fruitUUIDs)
                    annotation.labelPrimitives(flatten(cluster), "clusters");
            }
        }
    }
    // Render the annotations.
    std::string this_image_dir =  std::string("rendered_images/annotations");
    std::cout << this_image_dir;
    annotation.render(this_image_dir.c_str());
#endif





    return 0;
}
