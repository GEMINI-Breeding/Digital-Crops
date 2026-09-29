#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=220G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_geomval
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/geomval-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
unset DISPLAY
cmake -S . -B build-gpu -DCMAKE_BUILD_TYPE=Release > /dev/null
make -C build-gpu -j8 2>&1 | grep -E "error|Error" || true
cd build-gpu
# Same seed as the ray-traced frames_v15/cowpea_040_0000301, so the two annotation sets are
# directly comparable. High-res OBJ leaves, matching the render, because the leaf prototype
# affects the plant-architecture RNG stream and therefore the geometry itself.
for OBJ in 1 0; do
  echo "=== geom, leaf.use_obj_mesh=$OBJ ==="
  /usr/bin/time -f "wall %e s" ./SyntheticAutotuning geom ../config/baseline.cfg 301 \
      leaf.use_obj_mesh $OBJ output.folder ../geom_obj$OBJ/ 2>&1 \
      | grep -vE "Advancing time|addPolymeshObject" | tail -8
done
