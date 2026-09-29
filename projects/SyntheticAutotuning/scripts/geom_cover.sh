#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=01:30:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=120G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_gcover
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/gcover-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
unset DISPLAY
cd build-gpu
rm -rf ../geom_cover
# With every leaf labelled, non-background pixels in the ID image ARE the vegetation, so canopy
# cover is readable from the rasterized pass with no shading. The sweeps ran with label_leaves 0
# for speed, which is exactly why the cover overshoot was invisible to them.
# Two leaf scales: the library default the previous build used, and the widened one.
for LS in "0.09 0.12" "0.10 0.16"; do
  set -- $LS
  for SEED in 301 302 303 304; do
    ./SyntheticAutotuning geom ../config/baseline.cfg $SEED \
        leaf.use_obj_mesh 0 geom.label_leaves 1 \
        leaf.prototype_scale_min $1 leaf.prototype_scale_max $2 \
        output.folder ../geom_cover/ls${1}_${2}/ > /dev/null 2>&1
  done
  echo "done leaf_scale=$1-$2"
done
echo "GCOVER COMPLETE"
