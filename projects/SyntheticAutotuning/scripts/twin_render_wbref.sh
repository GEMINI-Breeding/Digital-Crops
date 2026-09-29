#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=01:30:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH -J twin_wbref
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_wbref-%j.out
# Camera white balance from the white reference (the light reaching the surfaces in view): the grey card under the rig
# LEDs, and the naive baseline scenes, rendered exactly as twin_render_baseline.sh / twin_greypatch.sh but into new
# folders so the renders made with the previous white balance are kept for comparison.
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh; unset DISPLAY
export OMP_NUM_THREADS=8
make -C build-gpu -j8 SyntheticAutotuning 2>&1 | grep -E "error|Built target SyntheticAutotuning" | head -5
cd build-gpu
W=/group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/twin_work
OUT=$W/wbcheck/greypatch_wbref; mkdir -p $OUT; echo "=== grey card ==="
./SyntheticAutotuning render ../config/baseline.cfg 1 camera.hfov 71.884 camera.height 1.5 camera.resolution_x 648 camera.resolution_y 512 camera.samples 30 \
  leaf.use_obj_mesh 0 canopy.per_plant_seed 1 canopy.library_defaults 1 canopy.layout_file $W/wbcheck/empty_layout.txt leaf.nitrogen_model 0 \
  soil.reflectance_scale 1.0 soil.spectrum_index 0 scene.load_rover 1 light.sun_flux 0 scene.grey_patch_size 0.25 \
  camera.exposure auto camera.white_balance auto post.white_balance 0 post.ccm_file "" post.highlight_knee 0 output.write_exr 1 output.folder $OUT/ 2>&1 | grep -E "ERROR|WARNING|wrote_exr|grey_patch" | head -4
for D in 2023-06-20 2023-06-27 2023-07-03; do
  B=$W/baseline_$D; echo "=== $B ==="; mkdir -p "$B/render_wbref"
  ./SyntheticAutotuning render ../config/baseline.cfg 1 camera.hfov 71.884 camera.height 1.5 leaf.use_obj_mesh 0 \
    canopy.per_plant_seed 1 canopy.library_defaults 1 canopy.layout_file "$B/layout.txt" \
    leaf.nitrogen_model 0 leaf.chlorophyll 30 leaf.carotenoid 7 leaf.anthocyanin 1 leaf.numberlayers 1.5 leaf.watermass 0.015 leaf.drymass 0.09 \
    leaf.specular_scale 0 soil.reflectance_scale 1.0 soil.spectrum_index 0 scene.load_rover 1 \
    camera.exposure auto camera.white_balance auto post.white_balance 0 post.ccm_file "" post.highlight_knee 0 \
    camera.flux_smoothing 30 scene.ground_subdiv 500 camera.samples 40 output.write_exr 1 output.write_site_ids 1 \
    output.folder "$B/render_wbref/" 2>&1 | grep -E "DIAG (library_defaults|canopy_top)|ERROR|WARNING|wrote " | head -6
done
echo "=== done ==="
