#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=220G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_spec
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/spec-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
make -C build-gpu -j8 2>&1 | grep -E " error" || true
cd build-gpu
# Rover restored. Enlarging the emitters (source_scale 2.0) was chosen to soften
# shadows, but it also inflated the specular lobe: 5.84% specular pixels against
# a real 0.83%, and 2.66% near-white against 0.28%. Walk it back and cut the
# leaf specular scale, checking colour at the same time.
for ss in 1.0 2.0; do
 for spec in 0.25 0.12; do
  echo "### source_scale=$ss specular=$spec rover=1"
  ./SyntheticAutotuning render ../config/baseline.cfg 201 \
    camera.resolution_x 900 camera.resolution_y 712 camera.samples 30 \
    light.source_scale $ss leaf.specular_scale $spec scene.load_rover 1 \
    output.folder ../frames_spec_${ss}_${spec}/ 2>&1 \
    | grep -oE "DIAG (rover_primitives|veg_cover)=[0-9.]+|wrote .*" | tr '\n' ' '
  echo
 done
done
