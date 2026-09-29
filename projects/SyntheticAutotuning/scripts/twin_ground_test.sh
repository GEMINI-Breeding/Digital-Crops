#!/bin/bash -l
# Ground resolution on the enlarged tile: the albedo map is 6 mm per texel over the bed, so the patches that sample it should
# be about that size. scene.ground_subdiv is per 3 m, so 500 over an 8 m tile is 1333 a side (6 mm) against 250's 1.2 cm.
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh; unset DISPLAY
PY=$PWD/env/bin/python
W=$PWD/twin_work/anim/2023-06-27_Plot298-MAGIC226
ARGS=$($PY -c "
import json; d=json.load(open('$W/ov.json')); print(' '.join(f'{k} {v}' for k,v in d.items()))")
LEAF=$(cat $W/leaf_overrides.txt)
cd build-gpu
for SUB in 500; do
  O=$W/tilt30_sub$SUB; mkdir -p $O
  echo "=== 30 deg, ground_subdiv $SUB on an 8 m tile ==="
  /usr/bin/time -f "render %E" ./SyntheticAutotuning render ../config/baseline.cfg 1 camera.hfov 59.8 camera.resolution_x 2048 \
    camera.resolution_y 2592 leaf.use_obj_mesh 1 canopy.per_plant_seed 1 leaf.nitrogen_model 1 output.write_exr 1 \
    output.write_site_ids 1 camera.samples 40 post.white_balance 0 camera.exposure auto scene.load_rover 1 \
    scene.rover_frame_scale 0.38 scene.rover_fender_scale 0.225 scene.rover_tyre_scale 0.29 scene.rover_wheel_scale 0.35 \
    scene.rover_specular_scale 0.5 scene.rover_specular_exponent 100 camera.flux_smoothing 30 scene.ground_subdiv $SUB \
    scene.ground_size_x 8 scene.ground_size_y 8 scene.soil_albedo_map $W/soil_albedo.bin canopy.layout_file $W/layout.txt \
    camera.tilt_deg 30 camera.tilt_azimuth_deg 0 camera.orbit_radius_m 0.95 $ARGS $LEAF output.folder "$O/" 2>&1 | grep -E "DIAG soil_albedo|render |ERROR|wrote " | head -4
done
