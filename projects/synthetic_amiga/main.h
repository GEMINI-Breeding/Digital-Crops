//
// Created by Heesup Yun on 7/27/23.
//

#ifndef HELIOS_MAIN_H
#define HELIOS_MAIN_H

// Field configuration
#define BED_HEIGHT 0.2
#define BED_WIDTH (BED_HEIGHT*10)
#define BED_LENGTH (BED_HEIGHT*20)


#include "json.hpp"

#include <random>
#include <string>
#include <type_traits>
#include <vector>

using json = nlohmann::json;

// Forward declarations
namespace helios {
    class Context;
    typedef unsigned int uint;
}

json loadParametersFromJson(const std::string& filename);

// Recursively sample all parameters with "sampling" key and add "sampled" values in-place
json sampleParametersToJson(int crop_index, const json& json_params, std::mt19937& rng);

// OBJ ground functions
std::vector<helios::uint> createObjGround(helios::Context& context, const json& sampled);
void generateMtlFile(const std::string& obj_path, float soil_color[3]);

#endif //HELIOS_MAIN_H

