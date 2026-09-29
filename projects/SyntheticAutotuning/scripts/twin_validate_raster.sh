#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=01:30:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH -J twin_valid
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_valid-%j.out

# Validates the CPU label rasterizer against the ray tracer: the same scene (same seed, same
# per-site plants) is rendered with output.write_site_ids so the ray-traced siteIndex label map
# can be compared pixel for pixel with the rasterizer's site map. Also renders with the rover so
# its silhouette can be aligned against the real rover mask to check the camera height.
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
unset DISPLAY
echo "=== node: $(hostname) ==="
nvidia-smi --query-gpu=name,driver_version --format=csv,noheader || true
cmake -S . -B build-gpu -DCMAKE_BUILD_TYPE=Release 2>&1 | grep -iE "optix|cuda|vulkan|backend" || true
make -C build-gpu -j8 SyntheticAutotuning 2>&1 | grep -E "error|Error|Built target SyntheticAutotuning" | head -20

OUT=/group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/twin_work/valid/
COMMON="camera.resolution_x 648 camera.resolution_y 512 camera.hfov 71.884 camera.height 1.55 canopy.age 30 leaf.use_obj_mesh 0 canopy.per_plant_seed 1 canopy.rows 2 canopy.plant_spacing_x 0.76 canopy.plant_spacing_y 0.25 canopy.germination_fraction_min 0.7 canopy.germination_fraction_max 0.7 leaf.nitrogen_model 0 output.write_exr 0"
cd build-gpu
echo "=== render (ray traced, site label map) ==="
./SyntheticAutotuning render ../config/baseline.cfg 11 $COMMON camera.samples 20 scene.load_rover 1 output.write_site_ids 1 output.write_leaf_ids 1 output.folder $OUT 2>&1 | grep -E "DIAG|SITE|primitives|wrote|WARNING|ERROR" | head -80
echo "=== raster (CPU) ==="
./SyntheticAutotuning raster ../config/baseline.cfg 11 $COMMON raster.load_rover 1 output.basename valid_0000011 output.folder $OUT 2>&1 | grep -E "DIAG|SITE|wrote|ERROR" | head -80
echo "=== done ==="
