#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=12:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=220G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_finalA
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/finalA-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
make -C build-gpu -j8 > /dev/null 2>&1
rm -rf frames_v14
cd build-gpu
# Ten frames, not six: the corrected 1280-native tiling leaves only ~14 candidate
# positions per frame, so 150 tiles from 6 frames were far less independent than
# the count suggested. More source scenes is the fix, not more tiles per scene.
for seed in 301 302 303 304 305 306 307 308 309 310; do
  ./SyntheticAutotuning render ../config/baseline.cfg $seed camera.samples 50 \
    output.folder ../frames_v14/ 2>&1 \
    | grep -oE "DIAG (veg_cover|rover_primitives|flowers_open)=[0-9.]+|wrote .*" | tr '\n' ' '
  echo
done
