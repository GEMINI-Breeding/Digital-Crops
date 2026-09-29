#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=00:40:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH -J twin_bisect
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_bisect-%j.out
# Why did the twin render come out magenta? Small renders of the untouched baseline, then one
# change at a time: procedural leaves, per-plant seeding, the calibrated camera.
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh; unset DISPLAY
OUT=/group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/twin_work/bisect
mkdir -p $OUT; cd build-gpu
SMALL="camera.resolution_x 648 camera.resolution_y 512 camera.samples 20 camera.exposure auto output.write_exr 1 canopy.age 30 scene.load_rover 0"
run() { name=$1; shift; echo "=== $name ==="; mkdir -p $OUT/$name; ./SyntheticAutotuning render ../config/baseline.cfg 3 $SMALL output.folder $OUT/$name/ "$@" 2>&1 | grep -E "DIAG (veg_cover|wb_factors|leafN|camera red)|primitives|ERROR|WARNING" | head -8; }
run A_baseline
run B_objmesh0 leaf.use_obj_mesh 0
run C_perplant leaf.use_obj_mesh 0 canopy.per_plant_seed 1
run D_camera leaf.use_obj_mesh 0 canopy.per_plant_seed 1 camera.hfov 71.884 camera.height 1.55
run E_nonitrogen leaf.use_obj_mesh 0 leaf.nitrogen_model 0
echo "=== done ==="
