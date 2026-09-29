#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_lift
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/lift-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
make -C build-gpu -j8 2>&1 | grep -E " error" || true
cd build-gpu
for bl in 0.000 0.015 0.030 0.045; do
  echo "### lift=$bl"
  ./SyntheticAutotuning render ../config/baseline.cfg 77 \
    camera.resolution_x 648 camera.resolution_y 512 camera.samples 25 \
    light.source_scale 2.0 light.diffuse_flux 0.10 \
    post.black_level $bl post.highlight_knee 0.55 \
    output.folder ../frames_lift_$bl/ 2>&1 | grep -oE "wrote .*" | tr '\n' ' '
  echo
done
