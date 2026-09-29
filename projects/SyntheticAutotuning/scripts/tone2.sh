#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=220G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_tone2
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/tone2-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
make -C build-gpu -j8 > /dev/null 2>&1
cd build-gpu
# The black-level lift was added to repair shadows crushed by the colour matrix
# clamping. The white-balance fix removed that clamping, so the lift is now
# obsolete and is the reason the frame has no dark pixels at all (0.1% below
# L=20 against a real 3.4%). The soil scale is also retested: it was previously
# masked by the highlight knee.
run () { # bl knee soil tag
  echo "### black=$1 knee=$2 soil=$3"
  ./SyntheticAutotuning render ../config/baseline.cfg 201 camera.samples 40 \
    post.black_level $1 post.highlight_knee $2 soil.reflectance_scale $3 \
    output.folder ../frames_t2_$4/ 2>&1 | grep -oE "wrote .*" | tr '\n' ' '; echo
}
run 0.000 0.55 1.0 a
run 0.000 0.00 1.0 b
run 0.000 0.55 0.6 c
run 0.010 0.55 0.6 d
