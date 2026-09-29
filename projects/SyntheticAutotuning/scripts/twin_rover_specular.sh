#!/bin/bash -l
# Rover material test after fixing the part labels (Tire_* rubber, Wheel_* metal rims, Fender, rest frame paint): two nadir
# renders with the metal given a highlight, and one tilted 30 deg view to check the mirror-tiled ground beyond the bed.
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh; unset DISPLAY
make -C build-gpu -j8 SyntheticAutotuning 2>&1 | grep -E "error|Built target SyntheticAutotuning" | head -3
PY=$PWD/env/bin/python
W=$PWD/twin_work/anim/2023-06-27_Plot298-MAGIC226
ARGS=$($PY -c "
import json; d=json.load(open('$W/ov.json')); print(' '.join(f'{k} {v}' for k,v in d.items()))")
LEAF=$(cat $W/leaf_overrides.txt)
ROVER="scene.rover_frame_scale 0.38 scene.rover_fender_scale 0.225 scene.rover_tyre_scale 0.29"
COMMON="leaf.use_obj_mesh 1 canopy.per_plant_seed 1 leaf.nitrogen_model 1 output.write_exr 1 output.write_site_ids 1 \
  camera.samples 40 post.white_balance 0 camera.exposure auto scene.load_rover 1 camera.flux_smoothing 30 \
  scene.soil_albedo_map $W/soil_albedo.bin canopy.layout_file $W/layout.txt $ROVER"
cd build-gpu
for spec in "0.5 100 0.35" "1.0 60 0.50"; do
  set -- $spec; S=$1; E=$2; WH=$3
  O=$W/rover3_${S}_${E}_${WH}; mkdir -p $O
  echo "=== nadir: specular $S exponent $E wheel $WH ==="
  ./SyntheticAutotuning render ../config/baseline.cfg 1 $COMMON camera.hfov 71.884 scene.ground_subdiv 500 \
    scene.rover_specular_scale $S scene.rover_specular_exponent $E scene.rover_wheel_scale $WH \
    $ARGS $LEAF output.folder "$O/" 2>&1 | grep -E "DIAG rover_materials|DIAG rover_specular|ERROR|wrote " | head -3
done
O=$W/tilt30_tiled; mkdir -p $O
echo "=== 30 deg, mirror-tiled ground ==="
./SyntheticAutotuning render ../config/baseline.cfg 1 $COMMON camera.hfov 59.8 camera.resolution_x 2048 camera.resolution_y 2592 \
  scene.ground_subdiv 250 scene.ground_size_x 8 scene.ground_size_y 8 camera.tilt_deg 30 camera.tilt_azimuth_deg 0 \
  camera.orbit_radius_m 0.95 scene.rover_specular_scale 0.5 scene.rover_specular_exponent 100 scene.rover_wheel_scale 0.35 \
  $ARGS $LEAF output.folder "$O/" 2>&1 | grep -E "DIAG rover_materials|DIAG camera_tilt|ERROR|wrote " | head -3
