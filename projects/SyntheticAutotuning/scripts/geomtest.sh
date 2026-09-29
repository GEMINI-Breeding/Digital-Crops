#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=220G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_geomtest
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/geomtest-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
unset DISPLAY
cmake -S . -B build-gpu -DCMAKE_BUILD_TYPE=Release > /dev/null
make -C build-gpu -j8 2>&1 | grep -E "error|Error" || true
cd build-gpu
echo "=== geom, low-res leaves, no rover ==="
/usr/bin/time -f "wall %e s" ./SyntheticAutotuning geom ../config/baseline.cfg 301 \
    leaf.use_obj_mesh 0 output.folder ../geom_v1/ 2>&1 | tail -20
