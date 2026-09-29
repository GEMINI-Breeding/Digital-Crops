#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_full
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/full-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
make -C build-gpu -j8 > /dev/null 2>&1
cd build-gpu
# Full sensor resolution so tiles are cut at NATIVE GSD (0.440 mm/px) with no
# resampling, exactly as the real tiles were.
for seed in 101 102 103; do
  ./SyntheticAutotuning render ../config/baseline.cfg $seed \
    camera.samples 50 output.folder ../frames_full/ 2>&1 \
    | grep -oE "DIAG (veg_cover|canopy_top_m)=[0-9.]+|built [0-9]+ cowpea|wrote .*" | tr '\n' ' '
  echo
done
