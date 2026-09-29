#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_tone
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/tone-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
make -C build-gpu -j8 > /dev/null 2>&1
cd build-gpu
for bl in 0.000 0.010 0.020 0.035; do
 for kn in 0.0 0.55; do
  echo "### black_level=$bl knee=$kn"
  ./SyntheticAutotuning render ../config/baseline.cfg 77 \
    camera.resolution_x 648 camera.resolution_y 512 camera.samples 20 \
    post.black_level $bl post.highlight_knee $kn \
    output.folder ../frames_tone_${bl}_${kn}/ 2>&1 | grep -oE "wrote .*" | tr '\n' ' '
  echo
 done
done
