#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=01:30:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH -J twin_baseline
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_baseline-%j.out
# Naive baseline renders: stock library cowpea on a nominal grid (twin_baseline_layout.py), the
# rig as documented (rover body, calibrated lens, 1.5 m), and stock appearance: library soil
# spectrum unscaled, LeafOptics default pigments, no specular, default rover reflectance, Helios
# auto exposure and auto white balance, no colour matrix, no highlight knee. Render quality
# (flux smoothing, ground tiling, samples) is the same as the twins'.
# usage: sbatch twin_render_baseline.sh <workdir> [<workdir> ...]   (each holds layout.txt)
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh; unset DISPLAY
export OMP_NUM_THREADS=8
make -C build-gpu -j8 SyntheticAutotuning 2>&1 | grep -E "error|Built target SyntheticAutotuning" | head -5
cd build-gpu
for W in "$@"; do
  echo "=== $W ==="; mkdir -p "$W/render"
  ./SyntheticAutotuning render ../config/baseline.cfg 1 camera.hfov 71.884 camera.height 1.5 leaf.use_obj_mesh 0 \
    canopy.per_plant_seed 1 canopy.library_defaults 1 canopy.layout_file "$W/layout.txt" \
    leaf.nitrogen_model 0 leaf.chlorophyll 30 leaf.carotenoid 7 leaf.anthocyanin 1 leaf.numberlayers 1.5 leaf.watermass 0.015 leaf.drymass 0.09 \
    leaf.specular_scale 0 soil.reflectance_scale 1.0 soil.spectrum_index 0 scene.load_rover 1 \
    camera.exposure auto camera.white_balance auto post.white_balance 0 post.ccm_file "" post.highlight_knee 0 \
    camera.flux_smoothing 30 scene.ground_subdiv 500 camera.samples 40 output.write_exr 1 output.write_site_ids 1 \
    output.folder "$W/render/" 2>&1 | grep -E "DIAG (library_defaults|canopy_top|plant_height)|ERROR|wrote " | head -5
done
echo "=== done ==="
