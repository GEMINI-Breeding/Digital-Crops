#ifndef SYNTHETICDATA_SAMPLE_TEST_MAIN_H
#define SYNTHETICDATA_SAMPLE_TEST_MAIN_H

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

template<typename T>
T sampleValue(const json& param, std::mt19937& rng) {
    std::string sampling = param["sampling"];
    
    if (sampling == "constant") {
        return static_cast<T>(param["value"]);
    }
    else if (sampling == "uniform") {
        T min_val = param["min"];
        T max_val = param["max"];
        if constexpr (std::is_integral_v<T>) {
            std::uniform_int_distribution<T> dist(min_val, max_val);
            return dist(rng);
        } else {
            std::uniform_real_distribution<T> dist(min_val, max_val);
            return dist(rng);
        }
    }
    else if (sampling == "normal") {
        T mean = param["mean"];
        T stddev = param["stddev"];
        std::normal_distribution<double> dist(static_cast<double>(mean), static_cast<double>(stddev));
        return static_cast<T>(dist(rng));
    }
    else if (sampling == "discrete") {
        auto values = param["values"];
        if (values.is_array() && !values.empty()) {
            std::uniform_int_distribution<size_t> dist(0, values.size() - 1);
            size_t index = dist(rng);
            return static_cast<T>(values[index]);
        }
    }
    
    // fallback - if no valid sampling method or parameters
    if (param.contains("min")) {
        return static_cast<T>(param["min"]);
    } else if (param.contains("value")) {
        return static_cast<T>(param["value"]);
    }
    return T{}; // default value
}

struct SampledParameters {
    int plant_count;
    int num_columns;
    int plant_age;
    int leaf_pitch;
    int camera_resolution_x;
    int camera_resolution_y;
    int chlorophyll_content;

    float ground_size_x;
    float ground_size_y;
    float plant_spacing_x;
    float plant_spacing_y;
    float flower_bud_break_probability;
    float camera_height;
    float focal_plane_distance_difference;
    float lens_diameter;
    float hfov;
    float distance_from_center;
    float azimuth_angle;
    float lookat_offset_x;
    float lookat_offset_y;
    float lookat_offset_z;
    float elevation_degrees;
    float azimuth_degrees;
    float ground_scale;

    bool use_obj_ground;
    
    std::string obj_file_path;
    std::string plant;
    std::string colorboard;
    std::string leaf_surface_spectral_data;
    std::string leaf_reflectivity;
    std::string leaf_transmissivity;
    std::string soil_surface_spectral_data;
    std::string soil_reflectivity;
    std::string camera_spectral_data;
    std::string camera_type;

};

SampledParameters sampleParameters(const json& json_params, std::mt19937& rng);
json buildSampledParametersJson(const SampledParameters& sampled);
void logSampledParameters(const SampledParameters& sampled, const std::string& filename);

json loadParametersFromJson(const std::string& filename);

// OBJ ground functions
std::vector<helios::uint> createObjGround(helios::Context& context, const SampledParameters& sampled);
void generateMtlFile(const std::string& obj_path, float soil_color[3]);

#endif // SYNTHETICDATA_SAMPLE_TEST_MAIN_H
