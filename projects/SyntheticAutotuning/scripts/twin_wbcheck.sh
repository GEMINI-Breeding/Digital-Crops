#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=00:40:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH -J twin_wbcheck
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_wbcheck-%j.out
# Controlled check of Helios auto white balance under the rig lighting: bare library soil, no plants,
# with and without the rover body; baseline appearance settings otherwise.
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh; unset DISPLAY
make -C build-gpu -j8 SyntheticAutotuning 2>&1 | grep -E "error|Built target SyntheticAutotuning" | head -3
cd build-gpu
W=/group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/twin_work/wbcheck
for R in 0 1; do for SUN in 3.0 0; do
  OUT=$W/rover${R}_sun${SUN}; mkdir -p $OUT; echo "=== rover $R sun $SUN ==="
  ./SyntheticAutotuning render ../config/baseline.cfg 1 camera.hfov 71.884 camera.height 1.5 camera.resolution_x 648 camera.resolution_y 512 camera.samples 20 \
    leaf.use_obj_mesh 0 canopy.per_plant_seed 1 canopy.library_defaults 1 canopy.layout_file $W/empty_layout.txt leaf.nitrogen_model 0 \
    soil.reflectance_scale 1.0 soil.spectrum_index 0 scene.load_rover $R light.sun_flux $SUN camera.exposure auto camera.white_balance auto post.white_balance 0 post.ccm_file "" \
    post.highlight_knee 0 output.write_exr 1 output.folder $OUT/ 2>&1 | grep -E "ERROR|wrote_exr" | head -2
done; done
echo "=== done ==="
