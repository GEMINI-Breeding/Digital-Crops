#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=220G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_covercal
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/covercal-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
unset DISPLAY
cmake -S . -B build-gpu -DCMAKE_BUILD_TYPE=Release > /dev/null
make -C build-gpu -j8 2>&1 | grep -E ' error|Error 1' || true
cd build-gpu
rm -rf ../frames_covercal
# Calibrate against the RENDER's own cover measure, with the OBJ leaves the dataset actually uses.
# The rasterized surrogate was calibrated with procedural leaves and does not transfer: it predicted
# 0.826 at germ 0.35 where the render gives 0.976.
#
# The full post-processing chain is left intact. An earlier attempt disabled the colour matrix to
# save time; the matrix boosts green, cover is an ExG threshold measured downstream of it, and germ
# 0.35 then read 0.724 against 0.976 with it enabled. camera.samples 4 rather than 50: cover is an
# ExG threshold on mean pixel colour, which is
# insensitive to Monte-Carlo noise, so the sample count can be cut without moving the statistic.
# Each germination value writes to its own folder: the output name is built from the seed, so a
# shared folder had every setting overwriting the same two files.
for GERM in 0.10 0.18 0.26 0.34 0.45 0.60; do
  for SEED in 501 502 503; do
    ./SyntheticAutotuning render ../config/baseline.cfg $SEED camera.samples 4 \
        canopy.germination_fraction_min $GERM canopy.germination_fraction_max $GERM \
        output.folder ../frames_covercal/g${GERM}/ 2>&1 \
      | grep -oE "DIAG veg_cover=[0-9.]+" | sed "s/^/germ=$GERM seed=$SEED /"
  done
done
echo "COVERCAL COMPLETE"
