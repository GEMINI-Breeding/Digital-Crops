#!/bin/bash -l
#SBATCH --account=publicgrp
#SBATCH --partition=low
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH -J twin_build2
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_build-%j.out
# Third CPU-only build tree (build-cpu2) for the leaf-shape keys, so jobs running build-cpu are not disturbed.
# rebuilt while jobs are executing the primary one. Select it with TWIN_BINARY=.../build-cpu2/SyntheticAutotuning.
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
export VULKAN_SDK=/group/bnbaileygrp/bnbailey/vulkan-sdk/1.3.290.0/x86_64
export PATH=$VULKAN_SDK/bin:$PATH LD_LIBRARY_PATH=$VULKAN_SDK/lib:$LD_LIBRARY_PATH CMAKE_PREFIX_PATH=$VULKAN_SDK:$CMAKE_PREFIX_PATH
echo "=== node $(hostname) ==="
cmake -S . -B build-cpu2 -DCMAKE_BUILD_TYPE=Release 2>&1 | grep -iE "vulkan|cuda|optix|backend|error" || true
make -C build-cpu2 -j16 SyntheticAutotuning 2>&1 | grep -E "error|Error|Built target SyntheticAutotuning" | head -20
ls -la build-cpu2/SyntheticAutotuning
