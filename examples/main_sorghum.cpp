#include "Visualizer.h"
#include "CanopyGenerator.h"
#include "SyntheticAnnotation.h"
#include "RadiationModel.h"
#include "SolarPosition.h"
#include "EnergyBalanceModel.h"

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

    int n_beds = config["n_beds"].as<int>(); 
    int n_rows = config["n_rows"].as<int>(); 

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

std::vector<uint> plant_sorghum(CanopyGenerator &canopygenerator, Context &context, YAML::Node config){
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


std::vector<uint> plant_crops(CanopyGenerator &canopygenerator, Context &context, YAML::Node config){
    // Canopy generator model
    //CanopyGenerator canopygenerator(&context);


    // Plant Sorghum based on the config locations
    int n_crops = config["crops"].size();
    std::vector<uint> UUIDs_total;
    uint plant_id = 0;
    for (int i = 0; i < config["crops"].size(); i++){
        int bed = config["crops"][i]["bed"].as<int>();
        int row = config["crops"][i]["row"].as<int>();
        // float x = bed * BED_WIDTH;
        // float y = row * BED_LENGTH;
        // float z = 0;
        vec3 origin(-BED_WIDTH / 2, -BED_LENGTH / 2, 0);

        float X = (281 - config["crops"][i]["x"].as<float>()) / 281 * 2 * BED_WIDTH;
        float Y = config["crops"][i]["y"].as<float>() / 376 * BED_LENGTH;
        // float Z = config["crops"][i]["Z"].as<float>();
        vec3 plant_origin = origin + make_vec3(X, Y, 0);

        //printf(config["crops"][i]["crop_type"].as<std::string>().c_str());
        std::cout << config["crops"][i]["crop_type"] << std::endl;
        if (config["crops"][i]["crop_type"].as<std::string>() == "Sorghum"){
            SorghumCanopyParameters parameters;
            parameters.canopy_origin = plant_origin;
            parameters.sorghum_stage = config["crops"][i]["growth_stage"].as<int>();
            plant_id = canopygenerator.sorghum(parameters, plant_origin); // Gererate a single Sorhgum plant


        }else if (config["crops"][i]["crop_type"].as<std::string>() == "Cowpea"){
            BeanParameters parameters;
            parameters.canopy_origin = plant_origin;
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
    //std::string yaml_path = path + "/python_scripts/config.yaml";
    std::string yaml_path = path + "/data/2023-06-20-P4-RGB_Plot_428.yaml";
    std::cout << yaml_path << std::endl;
    YAML::Node config = load_yaml(yaml_path);

    // OBJ 3D Model
    std::vector<uint> UUIDs_ground = make_field(context, obj_path, config);

    // Plant sorghum
    CanopyGenerator canopygenerator(&context);
#if 0
    std::vector<uint> UUIDs_leaves = plant_sorghum(canopygenerator, context, config);
#else
    std::vector<uint> UUIDs_leaves = plant_crops(canopygenerator, context, config);
#endif
    std::vector<uint> UUIDs_all = context.getAllUUIDs();
    
    // Get all UUIDs
    std::vector<uint> UUIDs_total;
    for( uint UUID : UUIDs_total ){
        std::vector<vec3> vertices = context.getPrimitiveVertices(UUID);
        vec3 vertex = vertices.at(0);
        float z = vertex.z;
        context.setPrimitiveData(UUID,"height",z);
    }

    context.loadXML("../xml/timeseries_CIMIS_Davis.xml");
    uint time = 12;
    float air_temperature = context.queryTimeseriesData("air_temperature", time);
    float air_humidity = context.queryTimeseriesData("humidity", time);
    float wind_speed = context.queryTimeseriesData("wind_speed", time);

    std::cout << "Ta = " << air_temperature << "; rh = " << air_humidity << "; U = " << wind_speed << std::endl;

    context.setPrimitiveData(UUIDs_all, "air_temperature", air_temperature);
    context.setPrimitiveData(UUIDs_all, "air_humidity", air_humidity);
    context.setPrimitiveData(UUIDs_all, "wind_speed", wind_speed);

    //** Set up Solar Position Model ** //
    SolarPosition sun(7, 31.256, 119.947, &context );
    float sky_LW = sun.getAmbientLongwaveFlux(air_temperature, air_humidity);
    float sun_PAR = sun.getSolarFluxPAR( 101000,air_temperature, air_humidity, 0.05 );
    float sun_NIR = sun.getSolarFluxNIR( 101000,air_temperature, air_humidity, 0.05 );
    float f_diff = sun.getDiffuseFraction( 101000,air_temperature, air_humidity, 0.05 );

    //*** Set up Radiation Model ***//
    RadiationModel radiation(&context);

    uint sourceID = radiation.addSunSphereRadiationSource( sun.getSunDirectionVector() ); //this will set to the default sun direction of vertical

    radiation.addRadiationBand("PAR");
    radiation.disableEmission("PAR");
    radiation.setSourceFlux(sourceID, "PAR", sun_PAR*(1.f-f_diff));
    radiation.setDiffuseRadiationFlux("PAR", sun_PAR*f_diff);
    radiation.setScatteringDepth( "PAR", 3);

    radiation.addRadiationBand("NIR");
    radiation.disableEmission("NIR");
    radiation.setSourceFlux(sourceID, "NIR", sun_NIR*(1.f-f_diff));
    radiation.setDiffuseRadiationFlux("NIR", sun_NIR*f_diff);
    radiation.setScatteringDepth( "NIR", 3);

    radiation.addRadiationBand("LW");
    radiation.setDiffuseRadiationFlux("LW", sky_LW);

    radiation.enforcePeriodicBoundary("xy");

    //set leaf radiative properties
    context.setPrimitiveData( UUIDs_leaves, "reflectivity_PAR", 0.05f );
    context.setPrimitiveData( UUIDs_leaves, "transmissivity_PAR", 0.05f );
    context.setPrimitiveData( UUIDs_leaves, "reflectivity_NIR", 0.4f );
    context.setPrimitiveData( UUIDs_leaves, "transmissivity_NIR", 0.4f );

    context.setPrimitiveData( UUIDs_ground, "reflectivity_PAR", 0.15f );
    context.setPrimitiveData( UUIDs_ground, "reflectivity_NIR", 0.35f );

    context.setPrimitiveData(UUIDs_ground, "twosided_flag",uint(0)); //only want ground to intercept radiation from the top

    radiation.updateGeometry();//geometry will not change throughout the day, so only update it once

    //*** Set Up Energy Balance Model ***//

    EnergyBalanceModel energybalance(&context);

    energybalance.addRadiationBand("PAR");
    energybalance.addRadiationBand("NIR");
    energybalance.addRadiationBand("LW");

    //*** Set Moisture Conductance ***//

    //for now, let's just assume we have constant stomatal conductance for the leaves and the ground is dry
    context.setPrimitiveData(UUIDs_leaves,"moisture_conductance",0.2f);

    //*** Run the Models ***//

    radiation.runBand( "PAR" );
    radiation.runBand( "NIR" );
    radiation.runBand("LW"); //note that we have not run the energy balance yet, so this is based on default temperatures

    energybalance.run();//note that this is based on longwave that was based on default temperatures, so it's not quite right yet

    //run these again to iteratively update. You could continue iterating depending on how accurate you want to be
    radiation.runBand("LW");
    energybalance.run();

    //*** Get the Temperature Distribution and Calculate the Crop Coefficient ***//

    float latent_flux = 0;
    //float ground_area = params.canopy_extent.x*params.canopy_extent.y;
    float ground_area = BED_HEIGHT*BED_WIDTH * config["n_beds"].as<int>()*config["n_rows"].as<int>();
    for( uint UUID : UUIDs_all ) {
        float E;
        context.getPrimitiveData(UUID, "latent_flux", E);
        float area = context.getPrimitiveArea(UUID);
        latent_flux += E * area / ground_area;
    }

    float ET = latent_flux; //W/m^2 = J/s/m^2
    ET = ET / 2264705.f * 3600; //mm H2O

    std::cout << "ET = " << ET << " mm" << std::endl;

    float ET0 = context.queryTimeseriesData("ET0", time);
    std::cout << "CIMIS ET0 = " << ET0 << " mm" << std::endl;

    std::cout << "kc = " << ET / ET0 << std::endl;

    context.writePrimitiveData( "temperature.txt", {"temperature"}, UUIDs_leaves, true);

    //Add some calculated primitive data called "dT" so we can visualize based on it
    for( uint UUID : UUIDs_all ) {
        float T;
        context.getPrimitiveData( UUID, "temperature", T);
        context.setPrimitiveData( UUID, "temperature_C", T-273.15);
        context.setPrimitiveData( UUID, "dT", T-air_temperature);
    }

    Visualizer visualizer(800);
    visualizer.hideWatermark();

    visualizer.buildContextGeometry(&context);

    visualizer.setCameraPosition(make_vec3(0, 0, 5), make_vec3(0, 0, 0));

#if 0
    visualizer.colorContextPrimitivesByData( "dT" );
    visualizer.setColorbarTitle("T-T_a_i_r");
#else
    visualizer.colorContextPrimitivesByData( "temperature_C" );
    visualizer.setColorbarTitle("Temperature (C)");
#endif
    visualizer.setColorbarFontSize(18);

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
