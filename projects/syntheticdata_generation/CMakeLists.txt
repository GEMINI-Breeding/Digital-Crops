# Helios standard CMakeLists.txt file version 1.8
if ( WIN32 )
    cmake_minimum_required(VERSION 3.15)
else()
    cmake_minimum_required(VERSION 3.15)
endif()

project(helios)

# CUDA 디버그 플래그 추가
if(CMAKE_BUILD_TYPE MATCHES Debug)
    set(CMAKE_CUDA_FLAGS "${CMAKE_CUDA_FLAGS} -g -G -O0")
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -g -O0")
endif()

#-------- USER INPUTS ---------#

#find_package(yaml-cpp REQUIRED)

#provide the path to Helios base directory, either as an absolute path or a path relative to the location of this file
set( BASE_DIRECTORY "../../libs/Helios" )

# Add another cmake file in libs/yaml-cpp to the project with binary directory
add_subdirectory(../../libs/yaml-cpp ${CMAKE_BINARY_DIR}/yaml-cpp)
# include_directories(libs/yaml-cpp/include)

#define the name of the executable to be created
set( EXECUTABLE_NAME "main" )

#provide name of source file(s) (separate multiple file names with semicolon)
#set( SOURCE_FILES "main_cowpea_yaml_grow.cpp" )
set( SOURCE_FILES "main.cpp;utils.cpp;field.cpp" )

#specify which plug-ins to use (separate plug-in names with semicolon)
#set( PLUGINS "visualizer;canopygenerator;radiation;syntheticannotation;solarposition;energybalance")
set( PLUGINS "visualizer;canopygenerator;syntheticannotation;solarposition;plantarchitecture;radiation;leafoptics")


#-------- DO NOT MODIFY ---------#
include( "${BASE_DIRECTORY}/core/CMake_project.txt" )

target_link_libraries(main PRIVATE "yaml-cpp")
