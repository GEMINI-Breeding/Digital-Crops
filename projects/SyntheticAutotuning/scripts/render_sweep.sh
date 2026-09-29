#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_sweep
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/sweep-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
cmake -S . -B build-gpu -DCMAKE_BUILD_TYPE=Release > /dev/null 2>&1
make -C build-gpu -j8 2>&1 | tail -1
cd build-gpu
for age in 45 60 75; do
  echo "########## age $age ##########"
  ./SyntheticAutotuning render ../config/baseline.cfg $age \
    camera.resolution_x 1296 camera.resolution_y 1024 camera.samples 50 \
    canopy.age $age post.ccm_file ../calib/ccm_camA_20230728.xml \
    output.folder ../frames_sweep/ 2>&1 | grep -E "DIAG|primitives|plants|wrote"
done
