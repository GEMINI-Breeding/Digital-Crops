#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=220G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_geomval2
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/geomval2-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
unset DISPLAY
cmake -S . -B build-gpu -DCMAKE_BUILD_TYPE=Release > /dev/null
make -C build-gpu -j8 2>&1 | grep -E "error|Error" || true
cd build-gpu
for OBJ in 1 0; do
  echo "=== geom, leaf.use_obj_mesh=$OBJ ==="
  /usr/bin/time -f "wall %e s" ./SyntheticAutotuning geom ../config/baseline.cfg 301 \
      leaf.use_obj_mesh $OBJ output.folder ../geom_obj$OBJ/ 2>&1 \
      | grep -vE "Advancing time|addPolymeshObject" | tail -6
done
# Raw EXR dump for the camera-pipeline replica: manual exposure so the dump is true radiance.
echo "=== render with raw EXR ==="
/usr/bin/time -f "wall %e s" ./SyntheticAutotuning render ../config/baseline.cfg 301 \
    camera.samples 50 camera.exposure manual output.write_exr 1 output.folder ../frames_exr/ 2>&1 \
    | grep -vE "Advancing time|addPolymeshObject" | tail -8
