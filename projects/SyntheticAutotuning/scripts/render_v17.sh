#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=08:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=220G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_v17
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/v17-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
unset DISPLAY
cmake -S . -B build-gpu -DCMAKE_BUILD_TYPE=Release > /dev/null
make -C build-gpu -j8 2>&1 | grep -E " error|Error 1" || true
cd build-gpu
rm -rf ../frames_v17
# Consolidated round: flower prototype back to the botanical 0.030, random per-plant azimuth,
# widened leaf scale, plus whatever the phenology sweep selects (written into baseline.cfg before
# this job is submitted). Raw EXR alongside so the camera chain stays tunable without re-rendering.
for SEED in 301 302 303 304 305 306 307 308 309 310; do
  ./SyntheticAutotuning render ../config/baseline.cfg $SEED camera.samples 50 \
      output.write_exr 1 output.folder ../frames_v17/ 2>&1 \
    | grep -oE "DIAG (veg_cover|flowers_open|flowers_closed|canopy_top_m)=[0-9.]+|wrote .*" | tr '\n' ' '
  echo
done
echo "V17 RENDER COMPLETE"
