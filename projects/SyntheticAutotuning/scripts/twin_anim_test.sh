#!/bin/bash -l
# Three test renders for the animation geometry: nadir (orientation check), and two tilted views with the camera walked
# down and in so it clears the rig, on an 8 m ground tile. Portrait sensor; rotate 90 deg in post for upright rows.
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh; unset DISPLAY
make -C build-gpu -j8 SyntheticAutotuning 2>&1 | grep -E "error|Built target SyntheticAutotuning" | head -3
PY=$PWD/env/bin/python
W=$PWD/twin_work/anim/2023-06-27_Plot298-MAGIC226
ARGS=$($PY -c "
import json; d=json.load(open('$W/ov.json')); print(' '.join(f'{k} {v}' for k,v in d.items()))")
LEAF=$(cat $W/leaf_overrides.txt)
COMMON="camera.hfov 59.8 camera.resolution_x 2048 camera.resolution_y 2592 leaf.use_obj_mesh 1 canopy.per_plant_seed 1 \
  leaf.nitrogen_model 1 output.write_exr 1 camera.samples 40 post.white_balance 0 camera.exposure auto scene.load_rover 1 \
  scene.rover_frame_scale 0.22 scene.rover_fender_scale 0.13 scene.rover_tyre_scale 0.17 camera.flux_smoothing 30 \
  scene.ground_subdiv 250 scene.ground_size_x 8 scene.ground_size_y 8 scene.soil_albedo_map $W/soil_albedo.bin \
  canopy.layout_file $W/layout.txt"
cd build-gpu
for spec in "nadir 0 1.55355" "t30_r095 30 0.95" "t15_r120 15 1.20"; do
  set -- $spec; NAME=$1; TILT=$2; RAD=$3
  O=$W/test_$NAME; mkdir -p $O
  echo "=== $NAME tilt $TILT radius $RAD ==="
  ./SyntheticAutotuning render ../config/baseline.cfg 1 $COMMON camera.tilt_deg $TILT camera.tilt_azimuth_deg 0 \
    camera.orbit_radius_m $RAD $ARGS $LEAF output.folder "$O/" 2>&1 | grep -E "DIAG camera_tilt|ERROR|wrote " | head -3
done
