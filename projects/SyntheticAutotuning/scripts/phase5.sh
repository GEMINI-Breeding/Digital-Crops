#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=08:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=220G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_phase5
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/phase5-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
unset DISPLAY
export YOLO_OFFLINE=1 ULTRALYTICS_OFFLINE=1
cmake -S . -B build-gpu -DCMAKE_BUILD_TYPE=Release > /dev/null
make -C build-gpu -j8 2>&1 | grep -E " error|Error 1" || true
mkdir -p opt
# Resumable: results are cached by a hash of the overrides and the study is sqlite-backed, so a
# run that outlives its allocation continues rather than restarting.
PHASE5_TRIALS=9 env/bin/python scripts/phase5_run.py
