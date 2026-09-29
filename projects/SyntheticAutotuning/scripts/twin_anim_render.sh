#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH -J twin_anim
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_anim-%j.out
# Renders for the twin animation on 2023-06-27 Plot298, in three beats:
#   descend 12 steps, camera walked from the rig's 1.55 m down to 0.95 m so the tilt to come clears the rig (12 rather
#           than 6: cross-fading six renders over a second and a half read as choppy, and this beat is pure camera move);
#   orbit   12 steps, 1 to 30 deg off nadir across the rows at 0.95 m;
#   grow    16 steps, +0 to +15 days at that viewpoint.
# Also renders the nadir pane the twin first appears as, in landscape, so the rig matches the tilted frames.
# Rover: part labels fixed (rubber tyres, metal rims), diffuse raised to the real rig's brightness, metal given a highlight.
# Ground: 8 m mirror-tiled at 6 mm patches, so a tilted view sees soil rather than void or a blurry smear.
# Portrait sensor (2048x2592 at 59.8 deg) so that rotating 90 deg in post gives upright rows at the real frame's pixel scale;
# the tilt starts at 1 deg because the camera's roll is undefined exactly at nadir. Ground tile enlarged to 8 m, rig kept.
# Raw EXRs only: one fixed gain is applied later in Python, so the sequence does not flicker.
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh; unset DISPLAY
make -C build-gpu -j8 SyntheticAutotuning 2>&1 | grep -E "error|Built target SyntheticAutotuning" | head -3
PY=$PWD/env/bin/python
W=${1:-$PWD/twin_work/anim/2023-06-27_Plot298-MAGIC226}
ARGS=$($PY -c "
import json; d=json.load(open('$W/ov.json')); print(' '.join(f'{k} {v}' for k,v in d.items()))")
LEAF=$(cat $W/leaf_overrides.txt)
ROVER="scene.rover_frame_scale 0.38 scene.rover_fender_scale 0.225 scene.rover_tyre_scale 0.29 scene.rover_wheel_scale 0.35 \
  scene.rover_specular_scale 0.5 scene.rover_specular_exponent 100"
SCENE="leaf.use_obj_mesh 1 canopy.per_plant_seed 1 leaf.nitrogen_model 1 output.write_exr 1 camera.samples 40 \
  post.white_balance 0 camera.exposure auto scene.load_rover 1 camera.flux_smoothing 30 scene.ground_subdiv 500 \
  scene.ground_size_x 8 scene.ground_size_y 8 scene.soil_albedo_map $W/soil_albedo.bin $ROVER"
COMMON="camera.hfov 59.8 camera.resolution_x 2048 camera.resolution_y 2592 $SCENE"
cd build-gpu
O="$W/nadir"; mkdir -p "$O"
echo "=== nadir (landscape, the pane the twin first appears as) ==="
./SyntheticAutotuning render ../config/baseline.cfg 1 $SCENE camera.hfov 71.884 canopy.layout_file "$W/layout.txt" \
  output.write_site_ids 1 $ARGS $LEAF output.folder "$O/" 2>&1 | grep -E "DIAG rover_materials|ERROR|wrote " | head -2
for i in $(seq 0 11); do
  RAD=$(awk "BEGIN{printf \"%.4f\", 1.55355 - (1.55355-0.95)*$i/11}")
  O="$W/descend_$(printf %02d $i)"; mkdir -p "$O"
  echo "=== descend $i radius $RAD ==="
  ./SyntheticAutotuning render ../config/baseline.cfg 1 $COMMON canopy.layout_file "$W/layout.txt" \
    camera.tilt_deg 1 camera.tilt_azimuth_deg 0 camera.orbit_radius_m $RAD $ARGS $LEAF output.folder "$O/" 2>&1 | grep -E "DIAG camera_tilt|ERROR|wrote " | head -2
done
for i in $(seq 0 11); do
  TILT=$(awk "BEGIN{printf \"%.3f\", 1 + 29*$i/11}")
  O="$W/orbit_$(printf %02d $i)"; mkdir -p "$O"
  echo "=== orbit $i tilt $TILT ==="
  ./SyntheticAutotuning render ../config/baseline.cfg 1 $COMMON canopy.layout_file "$W/layout.txt" \
    camera.tilt_deg $TILT camera.tilt_azimuth_deg 0 camera.orbit_radius_m 0.95 $ARGS $LEAF output.folder "$O/" 2>&1 | grep -E "DIAG camera_tilt|ERROR|wrote " | head -2
done
for d in $(seq 0 15); do
  G="$W/grow_$(printf %02d $d)"; mkdir -p "$G"
  echo "=== grow +$d d ==="
  ./SyntheticAutotuning render ../config/baseline.cfg 1 $COMMON canopy.layout_file "$W/layout_grow_$(printf %02d $d).txt" \
    camera.tilt_deg 30 camera.tilt_azimuth_deg 0 camera.orbit_radius_m 0.95 $ARGS $LEAF output.folder "$G/" 2>&1 | grep -E "ERROR|wrote " | head -2
done
echo "=== done ==="
