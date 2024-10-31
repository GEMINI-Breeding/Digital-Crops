#include "PlantArchitecture.h"
#include "Visualizer.h"

using namespace helios;

uint RedbudLeafPrototype( helios::Context* context_ptr, uint subdivisions=1, int flag=0 ){

    //uint leafID = context_ptr->addDiskObject( 10, make_vec3(0.5,0,0), make_vec2(1,1), nullrotation, RGB::green );
    std::vector<uint> UUIDs = context_ptr->loadOBJ( "../obj/RedbudLeaf.obj", nullorigin, 0, nullrotation, RGB::green, "ZUP", true );
    uint leafID = context_ptr->addPolymeshObject(UUIDs);
    return leafID;

}

int main(){

    float growth_respiration = 0;  //grams CHO respired to produce 1 gram of dry weight
    float maintainance_respiration_rate = 0; //grams CHO per gram dry weight per second

    Context context;

    context.seedRandomGenerator(60);
    PlantArchitecture plantarchitecture(&context);
    plantarchitecture.loadPlantModelFromLibrary("cowpea");
    plantarchitecture.buildPlantInstanceFromLibrary(nullorigin, 0);
    int Nplants = 1;

    //uint plant0 = plantarchitecture.addPlantInstance(nullorigin, 0); // Going dormant
    //context.addDisk( 20, nullorigin, make_vec2(2.5,2.5), nullrotation, RGB::white );

    bool render = true;
    int Nframes = 20;

    for( int i=0; i<Nframes; i++ ) {

        if( render ) {

            Visualizer vis(1080);
            vis.disableMessages();

            vis.setCameraPosition(make_SphericalCoord(0.3, 0.1 * M_PI, 0. * M_PI), make_vec3(0, 0, 0.05));
            //vis.setCameraPosition(make_SphericalCoord(2.2,0.31416,1.09957), make_vec3(0, 0, 0.4));

            //    vis.colorContextPrimitivesByData( "rank" );
            vis.setLightingModel(Visualizer::LIGHTING_PHONG_SHADOWED);
            //    vis.setLightDirection(make_vec3(0,0,1));

            vis.buildContextGeometry(&context);

            //        vis.plotInteractive();
            vis.plotUpdate(true);

            wait(1);

            std::stringstream framefile;
            framefile << "../frames/cowpea_growth" << std::setfill('0') << std::setw(3) << i << ".jpeg";
            vis.printWindow(framefile.str().c_str());

            vis.closeWindow();

        }
        plantarchitecture.advanceTime( 1 );
        std::cout << "Frame: " << i << std::endl;
    }

    Visualizer vis(1200);

    vis.setCameraPosition(make_SphericalCoord(2.2,0.31416,1.09957), make_vec3(0, 0, 0.4));
    vis.setLightingModel(Visualizer::LIGHTING_PHONG_SHADOWED);

    vis.buildContextGeometry(&context);

    vis.plotInteractive();


}