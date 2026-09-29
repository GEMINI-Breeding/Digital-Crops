#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=220G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_exr
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/exrdump-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
unset DISPLAY
cd build-gpu
rm -rf ../frames_exr
# Manual exposure so the EXR holds true radiance; the Python replica applies auto-exposure itself.
# The JPEG written alongside is the reference the replica is validated against, so it must go
# through the identical chain -- hence exposure=manual on both sides.
./SyntheticAutotuning render ../config/baseline.cfg 301 \
    camera.samples 50 camera.exposure manual output.write_exr 1 \
    output.folder ../frames_exr/ 2>&1 \
  | grep -vE "Advancing time|addPolymeshObject" | tail -10
ls -la ../frames_exr/
