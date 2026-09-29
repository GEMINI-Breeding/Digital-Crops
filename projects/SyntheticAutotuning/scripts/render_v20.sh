#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=10:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=220G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_v21
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/v21-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
unset DISPLAY
cmake -S . -B build-gpu -DCMAKE_BUILD_TYPE=Release > /dev/null
make -C build-gpu -j8 2>&1 | grep -E " error|Error 1" || true
cd build-gpu
rm -rf ../frames_v21
# Manual exposure: the JPEG the renderer writes here is nearly black and is NOT the dataset. The
# dataset is developed from the raw EXR by scripts/develop.py, which applies exposure in post.
# Ground masks are written for every frame so cover and foliage/soil colour are measured exactly
# rather than inferred from pixel colour.
for SEED in 601 602 603 604 605 606 607 608 609 610 611 612; do
  ./SyntheticAutotuning render ../config/baseline.cfg $SEED camera.samples 50 \
      output.folder ../frames_v21/ 2>&1 \
    | grep -oE "DIAG (germination_fraction)=[0-9.]+|built [0-9]+ cowpea|wrote .*" | tr '\n' ' '
  echo
done
echo "V21 RENDER COMPLETE"
