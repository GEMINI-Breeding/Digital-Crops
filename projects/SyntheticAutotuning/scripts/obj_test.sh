#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=01:30:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=180G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_objtest
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/objtest-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
make -C build-gpu -j8 2>&1 | grep -E " error" || true
cd build-gpu
echo "--- generic mesh ---"
/usr/bin/time -f "ELAPSED %e s" ./SyntheticAutotuning render ../config/baseline.cfg 201 \
  camera.resolution_x 648 camera.resolution_y 512 camera.samples 25 leaf.use_obj_mesh 0 \
  output.folder ../frames_objtest_gen/ 2>&1 | grep -oE "primitives|[0-9.]+M primitives|ELAPSED [0-9.]+ s|DIAG veg_cover=[0-9.]+" | tr '\n' ' '; echo
echo "--- high-res OBJ mesh ---"
/usr/bin/time -f "ELAPSED %e s" ./SyntheticAutotuning render ../config/baseline.cfg 201 \
  camera.resolution_x 648 camera.resolution_y 512 camera.samples 25 leaf.use_obj_mesh 1 \
  output.folder ../frames_objtest_obj/ 2>&1 | grep -oE "[0-9.]+M primitives|ELAPSED [0-9.]+ s|DIAG (veg_cover|veins_primitives)=[0-9.]+" | tr '\n' ' '; echo
