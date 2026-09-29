#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=120G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_cover
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/coversweep-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
unset DISPLAY
cmake -S . -B build-gpu -DCMAKE_BUILD_TYPE=Release > /dev/null
make -C build-gpu -j8 2>&1 | grep -E " error|Error 1" || true
cd build-gpu
rm -rf ../geom_cover2
# Stand density against leaf size. Germination fraction and row spacing change how much ground the
# canopy covers without touching plant morphology, so flower size and aspect -- which now match --
# should be undisturbed. Leaf scale is included because the widened 0.10-0.16 range is what
# overshot cover in the first place, and the narrower range may hold most of the structure-radius
# gain at lower closure.
for GERM in 0.35 0.50 0.65 0.80 0.90; do
  for SPY in 0.09 0.15; do
    for LEAF in "0.10 0.16" "0.10 0.13"; do
      set -- $LEAF
      TAG="g${GERM}_s${SPY}_l${1}-${2}"
      for SEED in 301 302 303; do
        ./SyntheticAutotuning geom ../config/baseline.cfg $SEED \
            leaf.use_obj_mesh 0 geom.label_leaves 1 \
            canopy.germination_fraction $GERM canopy.plant_spacing_y $SPY \
            leaf.prototype_scale_min $1 leaf.prototype_scale_max $2 \
            output.folder ../geom_cover2/$TAG/ 2>&1 | grep -oE "veg_cover=[0-9.]+" || true
        rm -f ../geom_cover2/$TAG/geom_040_0*/view00000/pixelID_combined.txt
      done
      echo "done $TAG"
    done
  done
done
echo "COVERSWEEP COMPLETE"
