#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=120G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_geomsweep
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/geomsweep-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
unset DISPLAY
cd build-gpu
rm -rf ../geom_sweep
# Flower prototype scale x inflorescence pitch, eight seeds each. Only a handful of flowers are
# unoccluded in any one frame, so the seed count is what makes the size distribution usable.
# Low-resolution leaves: the leaf mesh does not enter a flower's own bounding box, and this is
# ~34x faster than a ray-traced render.
for SCALE in 0.030 0.035 0.040 0.045 0.060; do
  for PITCH in "40 60" "80 90"; do
    set -- $PITCH
    for SEED in 301 302 303 304 305 306 307 308; do
      TAG="s${SCALE}_p${1}"
      ./SyntheticAutotuning geom ../config/baseline.cfg $SEED \
          leaf.use_obj_mesh 0 geom.label_leaves 0 \
          flower.prototype_scale $SCALE \
          flower.inflorescence_pitch_min $1 flower.inflorescence_pitch_max $2 \
          output.folder ../geom_sweep/$TAG/ > /dev/null 2>&1
      # The per-pixel ID map is 47 MB of text per run and is not used by the sweep.
      rm -f ../geom_sweep/$TAG/geom_040_0*/view00000/pixelID_combined.txt
    done
    echo "done $TAG"
  done
done
echo "SWEEP COMPLETE"
