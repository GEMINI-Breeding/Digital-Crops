#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=10:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=220G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_final7
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/final7-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
make -C build-gpu -j8 > /dev/null 2>&1
rm -rf frames_v11
cd build-gpu
for seed in 201 202 203 204 205 206; do
  ./SyntheticAutotuning render ../config/baseline.cfg $seed camera.samples 50 \
    output.folder ../frames_v11/ 2>&1 \
    | grep -oE "DIAG (wb_factors[^D]*|veg_cover=[0-9.]+|rover_primitives=[0-9]+)|wrote .*" | tr '\n' ' '
  echo
done
