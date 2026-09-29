#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=08:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=220G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_v18
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/v18-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
unset DISPLAY
cmake -S . -B build-gpu -DCMAKE_BUILD_TYPE=Release > /dev/null
make -C build-gpu -j8 2>&1 | grep -E " error|Error 1" || true
cd build-gpu
rm -rf ../frames_v18
# Verification round for the exposure/CCM correction: exposure_target drawn per scene from
# 0.115-0.185 (centre 0.15 from the raw-radiance sweep) and the colour matrix at full strength.
# Raw EXR alongside, so the camera chain stays tunable without re-rendering.
for SEED in 301 302 303 304 305 306 307 308 309 310; do
  ./SyntheticAutotuning render ../config/baseline.cfg $SEED camera.samples 50 \
      output.write_exr 1 output.folder ../frames_v18/ 2>&1 \
    | grep -oE "DIAG (veg_cover|flowers_open|exposure_target)=[0-9.]+|wrote .*" | tr '\n' ' '
  echo
done
echo "V18 RENDER COMPLETE"
