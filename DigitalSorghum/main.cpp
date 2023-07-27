#include "Visualizer.h"
#include "CanopyGenerator.h"

#include "main.h"

using namespace helios;


int make_field(Context &context){

    int n_beds = 2; //6
    int n_rows = 2; // 20

    std::vector<uint> UUIDs = context.loadOBJ("../../DigitalSorghum/obj/dirt_rocks.obj", make_vec3(0,0,0), BED_HEIGHT, nullrotation, RGB::white);

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

int plant_sorghum(Context &context){
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
    for(int bed = 0;bed < n_beds;bed++){
        for(int row=0;row<n_rows;row++){
            float x = bed * BED_WIDTH;
            float y = row * BED_LENGTH;
            float z = 0;
            vec3 origin(x,y,z);
            parameters.canopy_origin = origin;
            //canopygenerator.sorghum( parameters, origin ); // Gererate a single Sorhgum plant
            canopygenerator.buildCanopy( parameters);
        }
    }
}

int main(){
    Context context;

    // OBJ 3D Model
    make_field(context);

    // Plant sorghum
    plant_sorghum(context);

    // Set Visualizer
    Visualizer visualizer(800);
    visualizer.buildContextGeometry(&context);
    // Set the lighting model
    visualizer.setLightingModel(Visualizer::LIGHTING_PHONG_SHADOWED);

    visualizer.plotInteractive();
}
