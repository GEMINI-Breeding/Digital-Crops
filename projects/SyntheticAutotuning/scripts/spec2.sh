#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=220G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_spec2
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/spec2-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
make -C build-gpu -j8 > /dev/null 2>&1
cd build-gpu
# Black-level lift off (obsolete). The residual bright excess in 95%-vegetation
# tiles must be leaf specular, so sweep it and measure on TILES this time --
# the earlier sweep measured full frames, where bright soil dominated and
# masked the effect entirely.
for sp in 0.25 0.12 0.05 0.00; do
  echo "### specular=$sp"
  ./SyntheticAutotuning render ../config/baseline.cfg 201 camera.samples 40 \
    post.black_level 0.0 leaf.specular_scale $sp \
    output.folder ../frames_s2_$sp/ 2>&1 | grep -oE "wrote .*" | tr '\n' ' '; echo
done
