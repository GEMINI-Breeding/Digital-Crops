#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH -J twin_soil
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_soil-%j.out
# Render the fitted 06-20 layout once per library soil spectrum at half resolution, so the
# soil colour can be compared with the real frame from the raw EXRs. usage: sbatch twin_soil_sweep.sh <layout> <outdir>
set -e
LAYOUT=$1; OUT=$2
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh; unset DISPLAY
make -C build-gpu -j8 SyntheticAutotuning 2>&1 | grep -E "error|Built target SyntheticAutotuning" | head -5
mkdir -p "$OUT"; cd build-gpu
COMMON="camera.hfov 71.884 camera.height 1.55 camera.resolution_x 1296 camera.resolution_y 1024 camera.samples 20 leaf.use_obj_mesh 0 canopy.per_plant_seed 1 canopy.layout_file $LAYOUT leaf.nitrogen_model 1 scene.load_rover 0 output.write_exr 1 output.write_site_ids 1 post.white_balance 0 soil.reflectance_scale 0.09 camera.exposure auto"
for k in 0 1 2 3 4; do
  echo "=== soil $k ==="; mkdir -p "$OUT/soil$k"
  ./SyntheticAutotuning render ../config/baseline.cfg 1 $COMMON soil.spectrum_index $k output.folder "$OUT/soil$k/" 2>&1 | grep -E "DIAG (soil_index|veg_cover)|ERROR|wrote" | head -4
done
echo "=== done ==="
