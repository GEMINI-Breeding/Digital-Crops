#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=01:30:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=120G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_surro
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/surro-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
unset DISPLAY
cd build-gpu
rm -rf ../geom_surro
# Same seeds as frames_v17, same config, so the rasterized pass and the ray-traced pass describe
# the same ten scenes. Any statistic that disagrees is a surrogate fidelity limit, not noise.
for SEED in 301 302 303 304 305 306 307 308 309 310; do
  ./SyntheticAutotuning geom ../config/baseline.cfg $SEED \
      leaf.use_obj_mesh 0 geom.label_leaves 0 \
      output.folder ../geom_surro/ > /dev/null 2>&1
  rm -f ../geom_surro/geom_040_0*/view00000/pixelID_combined.txt
done
echo "SURROGATE CHECK COMPLETE"
