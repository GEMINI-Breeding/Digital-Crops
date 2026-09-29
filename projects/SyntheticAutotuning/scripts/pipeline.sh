#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=08:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_pipe
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/pipe-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
make -C build-gpu -j8 > /dev/null 2>&1
rm -rf frames_full
cd build-gpu
# Full sensor resolution: tiles are cut at native GSD, no resampling.
for seed in 201 202 203 204 205 206; do
  ./SyntheticAutotuning render ../config/baseline.cfg $seed \
    camera.samples 50 output.folder ../frames_full/ 2>&1 \
    | grep -oE "DIAG (veg_cover|canopy_top_m|flowers_open)=[0-9.]+|wrote .*" | tr '\n' ' '
  echo
done
