#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=01:30:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH -J twin_leaflets
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_leaflets-%j.out
# Leaf-level measures of the five fitted frames (SAM on the photos and on the twin renders, exact on the raster).
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh; unset DISPLAY
export OMP_NUM_THREADS=8
env/bin/python scripts/${TWIN_SCRIPT:-twin_leaflets.py} "$@"
