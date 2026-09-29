#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=05:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=220G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_alpha
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/alpha-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
make -C build-gpu -j8 2>&1 | grep -E " error" || true
cd build-gpu
for a in 1.00 0.75 0.55 0.40; do
  echo "### alpha=$a"
  ./SyntheticAutotuning render ../config/baseline.cfg 201 camera.samples 40 \
    post.ccm_strength $a output.folder ../frames_a_$a/ 2>&1 | grep -oE "wrote .*" | tr '\n' ' '
  echo
done
