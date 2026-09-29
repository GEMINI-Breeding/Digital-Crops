#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_soft
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/soft-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
make -C build-gpu -j8 2>&1 | grep -E " error" || true
cd build-gpu
for ss in 1 3 6; do
 for df in 0.35 1.0; do
  echo "### source_scale=$ss diffuse=$df"
  ./SyntheticAutotuning render ../config/baseline.cfg 77 \
    camera.resolution_x 648 camera.resolution_y 512 camera.samples 25 \
    light.source_scale $ss light.diffuse_flux $df \
    post.black_level 0.0 post.highlight_knee 0.55 \
    output.folder ../frames_soft_${ss}_${df}/ 2>&1 | grep -oE "wrote .*" | tr '\n' ' '
  echo
 done
done
