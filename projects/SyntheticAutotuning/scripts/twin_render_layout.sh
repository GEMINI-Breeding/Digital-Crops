#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH -J twin_render
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_render-%j.out

# Ray-trace a fitted layout: usage  sbatch scripts/twin_render_layout.sh <layout.txt> <outdir> [key value ...]
# Writes the raw EXR (for the Python developer), an auto-exposed JPEG for the eye, and the site,
# leaf and ground label maps, all at the camera of the rover calibration.
set -e
LAYOUT=$1; OUT=$2; shift 2
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
unset DISPLAY
echo "=== node: $(hostname) layout $LAYOUT out $OUT ==="
make -C build-gpu -j8 SyntheticAutotuning 2>&1 | grep -E "error|Built target SyntheticAutotuning" | head -5
mkdir -p "$OUT"
cd build-gpu
# post.white_balance 0: the camera now applies its white balance inside the renderer (the EXR
# arrives balanced), so the chain's own stage would apply it a second time and turn the JPEG
# magenta. soil.reflectance_scale 0.09 and soil 2: fitted on the 06-20 frame (twin/appearance).
COMMON="camera.hfov 71.884 camera.height 1.55 leaf.use_obj_mesh 0 canopy.per_plant_seed 1 canopy.layout_file $LAYOUT leaf.nitrogen_model 1 scene.load_rover 0 output.write_exr 1 output.write_site_ids 1 output.write_leaf_ids 1 camera.samples 40 post.white_balance 0 soil.reflectance_scale 0.09"
./SyntheticAutotuning render ../config/baseline.cfg 1 $COMMON output.folder "$OUT/" "$@" 2>&1 | grep -E "DIAG|SITE|primitives|wrote|WARNING|ERROR" | head -120
echo "=== done ==="
