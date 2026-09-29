#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=05:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=220G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_fix
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/fix-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
make -C build-gpu -j8 2>&1 | grep -E " error" || true
cd build-gpu
# Rover restored, white balance applied once and illuminant-aware, emitters back
# to their real size. Sweep leaf specular against the real 0.83% of pixels.
for spec in 0.25 0.15 0.08 0.04; do
  echo "### specular=$spec"
  ./SyntheticAutotuning render ../config/baseline.cfg 201 \
    camera.resolution_x 900 camera.resolution_y 712 camera.samples 30 \
    scene.load_rover 1 light.source_scale 1.0 post.white_balance 1 \
    leaf.specular_scale $spec output.folder ../frames_fix_$spec/ 2>&1 \
    | grep -oE "DIAG wb_factors[^D]*|wrote .*" | tr '\n' ' '
  echo
done
