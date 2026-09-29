#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_wb
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/wb-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
make -C build-gpu -j8 > /dev/null 2>&1
cd build-gpu
for wb in auto off; do
  echo "########## white_balance=$wb ##########"
  ./SyntheticAutotuning render ../config/baseline.cfg 42 \
    camera.resolution_x 400 camera.resolution_y 320 camera.samples 25 canopy.age 40 \
    camera.white_balance $wb post.ccm_file "" output.folder ../frames_wb_$wb/ 2>&1 \
    | grep -E "DIAG camera|wrote"
done
