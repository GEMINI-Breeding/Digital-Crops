#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=00:40:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH -J twin_greypatch
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_greypatch-%j.out
# A spectrally flat white card (DGK white) on bare soil, lit by the rig LEDs only (rover body on, sun off),
# rendered with the camera's white balance off and auto. No colour matrix, no plants.
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh; unset DISPLAY
make -C build-gpu -j8 SyntheticAutotuning 2>&1 | grep -E "error|Built target SyntheticAutotuning" | head -3
cd build-gpu
W=/group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/twin_work/wbcheck
for WB in off auto; do
  OUT=$W/greypatch_wb_$WB; mkdir -p $OUT; echo "=== white balance $WB ==="
  ./SyntheticAutotuning render ../config/baseline.cfg 1 camera.hfov 71.884 camera.height 1.5 camera.resolution_x 648 camera.resolution_y 512 camera.samples 30 \
    leaf.use_obj_mesh 0 canopy.per_plant_seed 1 canopy.library_defaults 1 canopy.layout_file $W/empty_layout.txt leaf.nitrogen_model 0 \
    soil.reflectance_scale 1.0 soil.spectrum_index 0 scene.load_rover 1 light.sun_flux 0 scene.grey_patch_size 0.25 \
    camera.exposure auto camera.white_balance $WB post.white_balance 0 post.ccm_file "" post.highlight_knee 0 output.write_exr 1 output.folder $OUT/ 2>&1 | grep -E "ERROR|WARNING|wrote_exr|grey_patch" | head -4
done
echo "=== done ==="
