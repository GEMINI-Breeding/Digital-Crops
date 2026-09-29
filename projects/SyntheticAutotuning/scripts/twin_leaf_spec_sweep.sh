#!/bin/bash -l
# Leaf specular sweep at exponent 30: scale 2x, 4x and 8x the fitted 0.035. The lobe is normalized, so at this width the
# peak is about a third of the exponent-100 peak at the same scale, and the sweep asks how much sheen the canopy needs.

# Same scene as the animation's nadir frame, so twin_work/anim/<frame>/nadir is the baseline to compare against.
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh; unset DISPLAY
PY=$PWD/env/bin/python
W=$PWD/twin_work/anim/2023-06-27_Plot298-MAGIC226
ARGS=$($PY -c "
import json; d=json.load(open('$W/ov.json')); print(' '.join(f'{k} {v}' for k,v in d.items()))")
LEAF=$(cat $W/leaf_overrides.txt)
SCENE="leaf.use_obj_mesh 1 canopy.per_plant_seed 1 leaf.nitrogen_model 1 output.write_exr 1 output.write_site_ids 1 \
  camera.samples 40 post.white_balance 0 camera.exposure auto scene.load_rover 1 camera.flux_smoothing 30 \
  scene.ground_subdiv 500 scene.ground_size_x 8 scene.ground_size_y 8 scene.soil_albedo_map $W/soil_albedo.bin \
  scene.rover_frame_scale 0.38 scene.rover_fender_scale 0.225 scene.rover_tyre_scale 0.29 scene.rover_wheel_scale 0.35 \
  scene.rover_specular_scale 0.5 scene.rover_specular_exponent 100 camera.hfov 71.884 canopy.layout_file $W/layout.txt"
cd build-gpu
# Peak brightness goes as scale x (exponent + 2), so these scales hold the current peak (0.035 at exponent 100) while the lobe
# widens, plus a stronger version of the widest one.
for S in 0.07 0.14 0.28; do
  O=$W/leafsweep_$S; mkdir -p $O
  echo "=== leaf specular exponent 30 scale $S ==="
  ./SyntheticAutotuning render ../config/baseline.cfg 1 $SCENE $ARGS $LEAF leaf.specular_exponent 30 leaf.specular_scale $S \
    output.folder "$O/" 2>&1 | grep -E "ERROR|wrote " | head -2
done
echo "=== done ==="
