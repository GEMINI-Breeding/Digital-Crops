#ifndef HELIOS_FIELD_H
#define HELIOS_FIELD_H

#include "json.hpp"
#include <string>
#include <vector>


// Forward declarations
namespace helios {
    class Context;
    typedef unsigned int uint;
}

namespace YAML {
    class Node;
}

using json = nlohmann::json;

class CanopyGenerator;

// Function to create field from OBJ file
std::vector<helios::uint> make_field(helios::Context &context, std::string obj_path, YAML::Node config);

// Function to plant crops based on YAML configuration
std::vector<helios::uint> plant_crops(CanopyGenerator &canopygenerator, helios::Context &context, YAML::Node config);


// Function to create OBJ-based ground
std::vector<helios::uint> createObjGround(helios::Context& context, const json& params);

std::vector<uint> make_field(helios::Context& context, const json& params);

#endif // HELIOS_FIELD_H
