#!/bin/bash -l
# Leaf specular test: the nadir twin with wider specular lobes (exponent 25 and 50) at the fitted scale 0.035. The lobe is
# normalized, so the scale fixes the total specular energy and the exponent only decides whether it lands as a tight bright
# peak on few pixels or a broader sheen over much of the leaf.
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
for pair in "25 0.13" "50 0.07" "25 0.20"; do
  set -- $pair; E=$1; S=$2
  O=$W/leafexp_${E}_${S}; mkdir -p $O
  echo "=== leaf specular exponent $E scale $S ==="
  ./SyntheticAutotuning render ../config/baseline.cfg 1 $SCENE $ARGS $LEAF leaf.specular_exponent $E leaf.specular_scale $S \
    output.folder "$O/" 2>&1 | grep -E "ERROR|wrote " | head -2
done
echo "=== done ==="
