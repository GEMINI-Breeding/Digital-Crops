#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH -J twin_leafgrid
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_leafgrid-%j.out
# Leaf optics and specular grid on one fitted frame (uniform chlorophyll, nitrogen model off),
# half resolution. usage: sbatch twin_leafgrid.sh <overrides.json> <workdir>
set -e
OVJSON=$1; W=$2
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh; unset DISPLAY
ARGS=$(env/bin/python -c "
import json; d=json.load(open('$OVJSON')); d=d.get('best_overrides', d)
print(' '.join(f'{k} {v}' for k,v in d.items()))")
cd build-gpu
for cab in 20 30 40 55; do for spec in 0.08 0.02; do
  OUTD="$W/grid_cab${cab}_spec${spec}"; mkdir -p "$OUTD"; echo "=== cab $cab spec $spec ==="
  ./SyntheticAutotuning render ../config/baseline.cfg 1 camera.hfov 71.884 camera.resolution_x 1296 camera.resolution_y 1024 camera.samples 20 leaf.use_obj_mesh 0 canopy.per_plant_seed 1 canopy.layout_file "$W/layout.txt" \
    leaf.nitrogen_model 0 leaf.chlorophyll $cab leaf.specular_scale $spec output.write_exr 1 output.write_site_ids 1 post.white_balance 0 soil.reflectance_scale 0.09 \
    camera.exposure auto scene.load_rover 1 camera.flux_smoothing 30 scene.ground_subdiv 500 scene.soil_albedo_map "$W/soil_albedo.bin" $ARGS output.folder "$OUTD/" 2>&1 | grep -E "ERROR|wrote_exr" | head -2
done; done
echo "=== done ==="
