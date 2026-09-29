#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_phen
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/phen-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
make -C build-gpu -j8 > /dev/null 2>&1
cd build-gpu
# Goal: flower density comparable to the real set AT the age where canopy top is
# ~0.54 m (age 40). Advancing flower initiation is the lever.
for fi in 12 18 24 30; do
  echo "### flower_initiation=$fi"
  ./SyntheticAutotuning render ../config/baseline.cfg 55 \
    camera.resolution_x 648 camera.resolution_y 512 camera.samples 15 \
    phenology.time_to_flower_initiation $fi \
    output.folder ../frames_phen_$fi/ 2>&1 \
    | grep -oE "DIAG (veg_cover|canopy_top_m|flowers_open|flowers_closed)=[0-9.]+" | tr '\n' ' '
  echo
  wc -l < ../frames_phen_$fi/*bbox*.txt 2>/dev/null | tr '\n' ' ' ; echo "boxes"
done
