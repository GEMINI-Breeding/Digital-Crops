#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=220G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_exr2
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/exrdump2-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
unset DISPLAY
cd build-gpu
rm -rf ../frames_exr_auto
# Auto exposure, so the JPEG is a normally-exposed image rather than a nearly-black one. The EXR
# is written after runBand and therefore carries the same auto-exposure gain, which is why the
# replica is run with exposure='manual' against it. Validating against a black frame proves
# nothing: every setting matches a black frame.
./SyntheticAutotuning render ../config/baseline.cfg 301 \
    camera.samples 50 camera.exposure auto output.write_exr 1 \
    output.folder ../frames_exr_auto/ 2>&1 \
  | grep -vE "Advancing time|addPolymeshObject" | grep -E "DIAG|wrote|applied"
