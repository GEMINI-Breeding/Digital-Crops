#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_dens
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/dens-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
make -C build-gpu -j8 > /dev/null 2>&1
cd build-gpu
# Cover must rise while canopy top stays near 0.54 m. Row count and in-row
# spacing add plants without advancing phenology; germination fills the gaps.
for rows in 2 3 4; do
 for germ in 0.7 1.0; do
  for spy in 0.13 0.09; do
    echo "### rows=$rows germ=$germ spacing_y=$spy"
    ./SyntheticAutotuning render ../config/baseline.cfg 11 \
      camera.resolution_x 400 camera.resolution_y 320 camera.samples 15 \
      canopy.rows $rows canopy.germination_fraction $germ canopy.plant_spacing_y $spy \
      output.folder ../frames_dens_r${rows}_g${germ}_s${spy}/ 2>&1 | grep -oE "DIAG (veg_cover|canopy_top_m)=[0-9.]+|built [0-9]+ cowpea" | tr '\n' ' '
    echo
  done
 done
done
