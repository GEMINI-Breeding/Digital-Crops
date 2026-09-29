#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_scat
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/scat-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
make -C build-gpu -j8 2>&1 | grep -E " error" || true
cd build-gpu
# Canopy interiors are lit mainly by light that has bounced between leaves.
# scatteringDepth was 2; real canopies need more. Also raise the side-light
# contribution, which fills from below the canopy top.
for sd in 2 5 8; do
 for sr in 0.2 0.6; do
  echo "### scatter_depth=$sd side_ratio=$sr"
  /usr/bin/time -f "%e s" ./SyntheticAutotuning render ../config/baseline.cfg 77 \
    camera.resolution_x 648 camera.resolution_y 512 camera.samples 20 \
    light.scattering_depth $sd light.side_ratio $sr light.diffuse_flux 0.35 \
    post.black_level 0.0 post.highlight_knee 0.55 \
    output.folder ../frames_scat_${sd}_${sr}/ 2>&1 | grep -oE "wrote .*|^[0-9.]+ s" | tr '\n' ' '
  echo
 done
done
