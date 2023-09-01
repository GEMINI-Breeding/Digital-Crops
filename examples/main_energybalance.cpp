#include "Visualizer.h"
#include "CanopyGenerator.h"
#include "RadiationModel.h"
#include "SolarPosition.h"
#include "EnergyBalanceModel.h"

using namespace helios;

int main() {

//    Context context;
//
//    context.loadXML("../xml/timeseries_CIMIS_Davis.xml");
//
//    uint UUID = context.addPatch();
//
//    for( int time=6; time<21; time++ ) {
//
//        printf("time - %02d:00\n",time);
//
//        //query data from our timeseries file and set primitive data accordingly
//        float air_temperature = context.queryTimeseriesData("air_temperature", time);
//        context.setPrimitiveData(UUID, "air_temperature", air_temperature);
//        float air_humidity = context.queryTimeseriesData("humidity", time);
//        context.setPrimitiveData(UUID, "air_humidity", air_humidity);
//
//        float radiation_SW = context.queryTimeseriesData("radiation", time);
//
//        //use solar position plug-in to get incoming longwave radiation
//        SolarPosition sun(&context);
//        float radiation_LW = sun.getAmbientLongwaveFlux(air_temperature, air_humidity);
//
//        //set the radiation flux based on measurement (shortwave) and calculated longwave
//        //we'll assume our reflectivity is 0.3
//        context.setPrimitiveData(UUID, "radiation_flux_total", radiation_SW*(1.f-0.3f) + radiation_LW);
//
//        //we'll assume our moisture conductance is 0.3
//        context.setPrimitiveData(UUID, "moisture_conductance", 0.3f);
//
//        //calculate and set our boundary-layer conductance based on measured wind speed
//        float wind_speed = context.queryTimeseriesData("wind_speed", time);
//        float gH = 0.166f + 0.5f * wind_speed;
//        context.setPrimitiveData(UUID, "boundarylayer_conductance", gH);
//
//        //set up and run the energy balance model
//        EnergyBalanceModel energybalance(&context);
//        energybalance.disableMessages();
//
//        energybalance.addRadiationBand("total");
//
//        energybalance.run();
//
//        //get the calculated latent heat flux and convert it into ET (mm)
//        float latent_flux;
//        context.getPrimitiveData(UUID, "latent_flux", latent_flux);
//        float ET = latent_flux; //W/m^2 = J/s/m^2
//        ET = ET / 2264705.f; //(kg H2O)/m^2/s
//        ET = ET * 3600; //(mol H2O)/m^2 --> 3600 sec/hr
//        ET = ET / 1000.f; //(m^3 H2O)/m^2  --> 1000 (kg H2O)/(m^3 H2O)
//        ET = ET * 1000.f; //(mm H2O)   --> 1000 mm/m
//
//        std::cout << "ET = " << ET << " mm" << std::endl;
//
//        float ET0 = context.queryTimeseriesData("ET0", time);
//        std::cout << "CIMIS ET0 = " << ET0 << " mm" << std::endl;
//
//        std::cout << "kc = " << ET / ET0 << std::endl;
//
//    }

    uint time = 12;

    Context context;

    // ** Build a Homogeneous Canopy ** //
    CanopyGenerator cgen(&context);

    HomogeneousCanopyParameters params;
    params.buffer = "xyz";
    params.leaf_subdivisions = make_int2(3,3);

    cgen.buildCanopy(params);

    std::vector<uint> UUIDs_leaves = cgen.getLeafUUIDs();

    //make a ground
    std::vector<uint> UUIDs_ground = context.addTile(make_vec3(0, 0, 0), params.canopy_extent, nullrotation,make_int2(100, 100));

    std::vector<uint> UUIDs_all = context.getAllUUIDs();

    //** Read in Timeseries Data **//

    context.loadXML("../xml/timeseries_CIMIS_Davis.xml");

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
    float ground_area = params.canopy_extent.x*params.canopy_extent.y;
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
        context.setPrimitiveData( UUID, "dT", T-air_temperature);
    }

    Visualizer visualizer(1000);

    visualizer.buildContextGeometry(&context);

    visualizer.colorContextPrimitivesByData( "dT" );
    visualizer.setColorbarTitle("T-T_a_i_r");
    visualizer.setColorbarFontSize(18);

    visualizer.plotInteractive();

}
