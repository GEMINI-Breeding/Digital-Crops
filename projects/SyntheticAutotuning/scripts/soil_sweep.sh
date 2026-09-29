#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_soil
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/soil-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
make -C build-gpu -j8 > /dev/null 2>&1
cd build-gpu
for sc in 1.0 0.70 0.50 0.35; do
  echo "### soil_scale=$sc"
  ./SyntheticAutotuning render ../config/baseline.cfg 77 \
    camera.resolution_x 648 camera.resolution_y 512 camera.samples 20 \
    soil.reflectance_scale $sc output.folder ../frames_soil_$sc/ 2>&1 | grep -oE "wrote .*" | tr '\n' ' '
  echo
done
