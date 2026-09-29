#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=120G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_fdens
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/fdens-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
unset DISPLAY
cmake -S . -B build-gpu -DCMAKE_BUILD_TYPE=Release > /dev/null
make -C build-gpu -j8 2>&1 | grep -E " error|Error 1" || true
cd build-gpu
rm -rf ../geom_fdens
# v21's germination (0.25-0.85) fixed canopy cover but halved flower count: 3.70 boxes/tile against
# a real 7.57, and cost 4.7 SE of mAP against v18. Fewer plants carry fewer flowers, so the count
# has to be restored per plant. Two levers: how often a bud breaks, and how long the plant has been
# flowering by the time it is imaged.
#
# Screened on the rasterized pass, which is valid here: these are geometric object statistics at a
# fixed leaf prototype, the regime where surrogate predictions transferred to the renders before.
for BUD in "0.10 0.15" "0.20 0.28" "0.35 0.45"; do
  for INIT in 19 15; do
    set -- $BUD
    TAG="b${1}-${2}_i${INIT}"
    for SEED in 701 702 703 704 705 706; do
      ./SyntheticAutotuning geom ../config/baseline.cfg $SEED \
          leaf.use_obj_mesh 0 geom.label_leaves 0 \
          flower.bud_break_prob_min $1 flower.bud_break_prob_max $2 \
          phenology.time_to_flower_initiation $INIT \
          output.folder ../geom_fdens/$TAG/ > /dev/null 2>&1
      rm -f ../geom_fdens/$TAG/geom_040_0*/view00000/pixelID_combined.txt
    done
    echo "done $TAG"
  done
done
echo "FDENS COMPLETE"
