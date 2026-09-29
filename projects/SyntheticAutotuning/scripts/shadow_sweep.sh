#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_shad
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/shad-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
make -C build-gpu -j8 2>&1 | grep -E "error" || true
cd build-gpu
# Roll the CCM off below ylo..yhi, with the pedestal now OFF: prevent the
# negatives instead of lifting them afterwards.
for lo in 0.02 0.05 0.09; do
 for hi in 0.12 0.20; do
  echo "### lo=$lo hi=$hi"
  ./SyntheticAutotuning render ../config/baseline.cfg 77 \
    camera.resolution_x 648 camera.resolution_y 512 camera.samples 20 \
    post.ccm_shadow_lo $lo post.ccm_shadow_hi $hi \
    post.black_level 0.0 post.highlight_knee 0.55 \
    output.folder ../frames_shad_${lo}_${hi}/ 2>&1 | grep -oE "wrote .*" | tr '\n' ' '
  echo
 done
done
