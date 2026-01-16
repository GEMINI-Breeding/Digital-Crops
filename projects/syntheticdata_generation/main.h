//
// Created by Heesup Yun on 7/27/23.
//

#ifndef HELIOS_MAIN_H
#define HELIOS_MAIN_H

#include <random>
#include <string>
#include <type_traits>
#include <vector>

// Forward declarations
namespace helios {
    class Context;
    typedef unsigned int uint;
}


// Global debug flag
extern bool g_debug_mode;

// Debug print macro - expands __FILE__ and __LINE__ at call site
// Usage: DEBUG_PRINT() or DEBUG_PRINT("message")
#define DEBUG_PRINT(...) do { \
    if (g_debug_mode) { \
        printf("%s:%d", __FILE__, __LINE__); \
        if (sizeof(#__VA_ARGS__) > 1) printf(" - " __VA_ARGS__); \
        printf("\n"); \
    } \
} while(0)

#endif //HELIOS_MAIN_H

