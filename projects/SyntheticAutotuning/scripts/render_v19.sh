#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=10:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=220G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_v19
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/v19-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
unset DISPLAY
cmake -S . -B build-gpu -DCMAKE_BUILD_TYPE=Release > /dev/null
make -C build-gpu -j8 2>&1 | grep -E " error|Error 1" || true
cd build-gpu
rm -rf ../frames_v19
# Ground-cover round: germination fraction drawn per scene from 0.35-0.90, sampling the steep part
# of the cover response instead of the saturated plateau. Fourteen frames rather than ten, because
# sparser stands render faster and the tiler needs a wide candidate pool to select against the real
# cover quantiles.
for SEED in 401 402 403 404 405 406 407 408 409 410 411 412 413 414; do
  ./SyntheticAutotuning render ../config/baseline.cfg $SEED camera.samples 50 \
      output.write_exr 1 output.folder ../frames_v19/ 2>&1 \
    | grep -oE "DIAG (veg_cover|germination_fraction|exposure_target|flowers_open)=[0-9.]+|wrote .*" | tr '\n' ' '
  echo
done
echo "V19 RENDER COMPLETE"
