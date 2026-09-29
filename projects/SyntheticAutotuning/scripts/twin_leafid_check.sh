#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH -J leafid_check
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/leafid_check-%j.out
# Regression check for the leaf-ID map: the assignment used to sit inside the nitrogen-driven spectrum branch, so a run
# giving its leaves one uniform spectrum wrote <base>_leafid.txt as all zeros without complaint. Renders the fitted 06-20
# layout with a uniform leaf colour -- the configuration that used to fail -- and prints the ID count.
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh; unset DISPLAY
W=$PWD/twin_work/2023-06-20_Plot286-MAGIC083_size
O=$PWD/twin_work/leafid_check
mkdir -p $O
ARGS=$(env/bin/python -c "
import json; d=json.load(open('$W/ov.json')); print(' '.join(f'{k} {v}' for k,v in d.items()))")
cd build-gpu
./SyntheticAutotuning render ../config/baseline.cfg 1 camera.hfov 71.884 canopy.per_plant_seed 1 \
  canopy.layout_file $W/layout.txt output.write_exr 0 output.write_leaf_ids 1 camera.samples 4 \
  camera.exposure auto scene.load_rover 0 $ARGS \
  leaf.nitrogen_model 0 leaf.chlorophyll 70.0 leaf.specular_scale 0.02 \
  output.folder $O/ 2>&1 | grep -E "DIAG leaf_object_ids|ERROR|wrote"
echo "=== leafid check done ==="
