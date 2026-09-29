#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=120G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_phen
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/phensweep-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
unset DISPLAY
cd build-gpu
rm -rf ../geom_phen
# Two open questions at once, both cheap now:
#  - flowers_per_peduncle: pinned to 1 earlier because clusters looked wrong, which is now
#    believed to have been the oversized flowers. 1-3 is the library (and botanical) value.
#  - time_to_flower_opening: how long a bud stays closed. The scene builds 76% closed flowers
#    against an estimated ~33% in the real annotations, and this is the parameter that sets it.
for FPP in 1 3; do
  for OPEN in 2 3 5; do
    for SEED in 301 302 303 304 305 306 307 308; do
      ./SyntheticAutotuning geom ../config/baseline.cfg $SEED \
          leaf.use_obj_mesh 0 geom.label_leaves 0 \
          flower.flowers_per_peduncle_min 1 flower.flowers_per_peduncle_max $FPP \
          phenology.time_to_flower_opening $OPEN \
          output.folder ../geom_phen/fpp${FPP}_open${OPEN}/ > /dev/null 2>&1
      rm -f ../geom_phen/fpp${FPP}_open${OPEN}/geom_040_0*/view00000/pixelID_combined.txt
    done
    echo "done fpp=$FPP open=$OPEN"
  done
done
echo "PHEN SWEEP COMPLETE"
