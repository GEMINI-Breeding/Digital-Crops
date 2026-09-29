#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH -J twin_rmany
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_rmany-%j.out
# Ray-trace several fitted layouts in one job. usage: sbatch twin_render_many.sh <overrides.json> <workdir1> [<workdir2> ...]
# Each workdir holds layout.txt; the render lands in <workdir>/render_rover/. Scene: rover on
# (it shrouds the plot over the LED rig), camera flux smoothing, 6 mm ground tiling.
set -e
OVJSON=$1; shift
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh; unset DISPLAY
make -C build-gpu -j8 SyntheticAutotuning 2>&1 | grep -E "error|Built target SyntheticAutotuning" | head -5
ARGS=$(env/bin/python -c "
import json,sys; d=json.load(open('$OVJSON')); d=d.get('best_overrides', d)
print(' '.join(f'{k} {v}' for k,v in d.items()))")
cd build-gpu
for W in "$@"; do
  # with the frame's own soil when its albedo map exists (twin/soil.py), into render_soil/; else render_rover/
  SOIL=""; OUTD="$W/render_rover"
  if [ -f "$W/soil_albedo.bin" ]; then SOIL="scene.soil_albedo_map $W/soil_albedo.bin"; OUTD="$W/render_soil"; fi
  # per-frame leaf optics and specular (leaf_overrides.txt, written from the frame's foliage colour)
  if [ -f "$W/leaf_overrides.txt" ]; then SOIL="$SOIL $(cat $W/leaf_overrides.txt)"; fi
  echo "=== $W ($OUTD) ==="; mkdir -p "$OUTD"
  ./SyntheticAutotuning render ../config/baseline.cfg 1 camera.hfov 71.884 leaf.use_obj_mesh 0 canopy.per_plant_seed 1 canopy.layout_file "$W/layout.txt" \
    leaf.nitrogen_model 1 output.write_exr 1 output.write_site_ids 1 output.write_leaf_ids 1 camera.samples 40 post.white_balance 0 soil.reflectance_scale 0.09 \
    camera.exposure auto scene.load_rover 1 scene.rover_frame_scale 0.22 scene.rover_fender_scale 0.13 scene.rover_tyre_scale 0.17 camera.flux_smoothing 30 scene.ground_subdiv 500 $ARGS $SOIL output.folder "$OUTD/" 2>&1 | grep -E "DIAG (canopy_top|flux_smoothing|rover_primitives|soil_albedo)|ERROR|wrote" | head -5
done
echo "=== done ==="
