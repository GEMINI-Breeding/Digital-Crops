#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=220G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_verify
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/verify-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
unset DISPLAY
cd build-gpu
# Geometry pass at the calibrated values, including the widened leaf scale, over more seeds than
# the sweep used so the open-flower size has a usable sample.
rm -rf ../geom_verify
for SEED in 301 302 303 304 305 306 307 308 309 310 311 312; do
  ./SyntheticAutotuning geom ../config/baseline.cfg $SEED \
      leaf.use_obj_mesh 0 geom.label_leaves 0 \
      output.folder ../geom_verify/calibrated/ > /dev/null 2>&1
  rm -f ../geom_verify/calibrated/geom_040_0*/view00000/pixelID_combined.txt
done
echo "GEOM VERIFY COMPLETE"
# Full ray-traced renders at the calibrated values, for tiling and appearance comparison.
rm -rf ../frames_v16
for SEED in 301 302 303 304 305 306 307 308 309 310; do
  ./SyntheticAutotuning render ../config/baseline.cfg $SEED camera.samples 50 \
      output.folder ../frames_v16/ 2>&1 \
    | grep -oE "DIAG (veg_cover|flowers_open|flowers_closed)=[0-9.]+|wrote .*" | tr '\n' ' '
  echo
done
echo "RENDER COMPLETE"
