#include "Visualizer.h"
#include "CanopyGenerator.h"

using namespace helios;

int make_field(Context &context){

    const float bed_height = 0.2;

    int n_beds = 2; //6
    int n_rows = 2; // 20

    std::vector<uint> UUIDs = context.loadOBJ("../../DigitalSorghum/obj/dirt_rocks.obj", make_vec3(0,0,0),bed_height,nullrotation,RGB::white);

    for(int bed = 0;bed < n_beds;bed++){
        for(int row=0;row<n_rows;row++){
            float x = bed*bed_height*10;
            float y = row*bed_height*20;
            float z = 0;
            std::vector<uint> UUIDs_copy = context.copyPrimitive(UUIDs);
            context.translatePrimitive(UUIDs_copy, make_vec3(x,y,z));
        }
    }
}



int main(){
    Context context;

    // OBJ 3D Model
    make_field(context);

    // Canopy generator model
    CanopyGenerator canopygenerator(&context);

    //Declare the parameter set for VSP grapevine
    SorghumCanopyParameters parameters;
    parameters.plant_count = make_int2(1,1);

    //Variable defining the location of the plant
    vec3 origin(0,0,0);

    //Add the sorghum geometry to the Context
    canopygenerator.sorghum( parameters, origin );


    // Set Visualizer
    Visualizer visualizer(800);
    visualizer.buildContextGeometry(&context);
    // Set the lighting model
    visualizer.setLightingModel(Visualizer::LIGHTING_PHONG_SHADOWED);

    visualizer.plotInteractive();
}
