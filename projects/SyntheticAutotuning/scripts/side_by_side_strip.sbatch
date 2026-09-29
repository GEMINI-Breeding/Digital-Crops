#!/bin/bash
#SBATCH --job-name=side_by_side
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=250G
#SBATCH --time=3:00:00
#SBATCH --output=%x-%j.log
# Trial 18's canopy peaks near 60 GB during the camera pixel-labelling pass, which is more than an
# interactive 64 GB allocation can hold. Submitted separately so the measurement gets its own memory.
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
exec env/bin/python scripts/side_by_side_strip.py
