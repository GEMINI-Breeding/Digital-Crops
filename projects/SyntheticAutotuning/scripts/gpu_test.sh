#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_gputest
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/gputest-%j.out

set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh

echo "=== node: $(hostname) ==="
nvidia-smi --query-gpu=name,driver_version --format=csv,noheader || true
echo "nvcc: $(command -v nvcc || echo MISSING)"

# The login node has no CUDA, so cmake there selects the Vulkan software-BVH
# fallback -- which returns NaN for every camera pixel once plant geometry is in
# the scene. Configure a SEPARATE build tree here so the CUDA/OptiX backend is
# picked up without clobbering the login-node build.
rm -rf build-gpu; cmake -S . -B build-gpu -DCMAKE_BUILD_TYPE=Release 2>&1 | grep -iE "optix|cuda|vulkan|backend" || true
make -C build-gpu -j8 2>&1 | tail -3

cd build-gpu
echo "=== small render ==="
./SyntheticAutotuning render ../config/baseline.cfg 7 \
  camera.resolution_x 400 camera.resolution_y 320 camera.samples 20 canopy.age 30 \
  post.ccm_file "" output.folder ../frames_gpu/ 2>&1 | grep -E "DIAG|primitives|wrote|WARNING" | head
