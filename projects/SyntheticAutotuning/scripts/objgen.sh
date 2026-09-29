#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=12:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=220G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_objgen
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/objgen-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
make -C build-gpu -j8 > /dev/null 2>&1
rm -rf frames_objfinal
cd build-gpu
for seed in 201 202 203 204 205 206; do
  /usr/bin/time -f "ELAPSED %e s" ./SyntheticAutotuning render ../config/baseline.cfg $seed \
    camera.samples 50 leaf.use_obj_mesh 1 output.folder ../frames_objfinal/ 2>&1 \
    | grep -oE "[0-9.]+M primitives|DIAG (veg_cover|flowers_open)=[0-9.]+|ELAPSED [0-9.]+ s|wrote .*" | tr '\n' ' '
  echo
done
