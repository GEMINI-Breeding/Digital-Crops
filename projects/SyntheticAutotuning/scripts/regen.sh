#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=08:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_regen
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/regen-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
make -C build-gpu -j8 > /dev/null 2>&1
rm -rf frames_full2
cd build-gpu
# Same six scenes as frames_full, but WITH the black-level pedestal and highlight
# knee. frames_full predates that fix, so the tiles cut from it still carry the
# CCM shadow crush (28.6 % of pixels below L=10 against a real 0.6 %).
for seed in 201 202 203 204 205 206; do
  ./SyntheticAutotuning render ../config/baseline.cfg $seed \
    camera.samples 50 output.folder ../frames_full2/ 2>&1 \
    | grep -oE "DIAG (veg_cover|flowers_open)=[0-9.]+|wrote .*" | tr '\n' ' '
  echo
done
