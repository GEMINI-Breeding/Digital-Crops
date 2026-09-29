#!/bin/bash -l
#SBATCH --account=publicgrp
#SBATCH --partition=low
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=32
#SBATCH --mem=64G
#SBATCH -J twin_rate
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_rate-%j.out
# The _final refit with the blade's expansion decoupled from the petiole's elongation: canopy.leaf_expansion_rate
# 0.5 (a blade finishes in two days) against canopy.elongation_rate 0.05 (a petiole takes twenty). Under the
# library's single rate the two advance together, so a half-grown node sits at half the petiole's reach carrying a
# quarter of its blade area -- a small leaf already pushed outward, which is the hole in the middle of the plant.
# Measured on blade pixels against the photograph, the split cuts the radial-profile distance from 1.47 to 0.62.
# Organ sizes are pinned as before, since the mature ones already match the hand labels (blade p90 1.02x, petiole
# 1.05x). Note elongation_rate drives the internode too -- the petiole elongates on the shoot's internode rate by
# design -- so the internodes slow with it. set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
export TWIN_WORKERS=$SLURM_CPUS_PER_TASK
export TWIN_BINARY=$PWD/build-cpu2/SyntheticAutotuning
TAG=${1:-_rate}
OV=${2:-twin_work/rate_refit_ov.json}
for FR in 2023-06-20_Plot286-MAGIC083 2023-06-20_Plot201-MAGIC262 2023-06-27_Plot286-MAGIC083 2023-06-27_Plot298-MAGIC226 2023-07-03_Plot286-MAGIC083; do
  D=${FR%%_*}; P=${FR#*_}
  echo "=== $FR ==="
  env/bin/python scripts/twin_fit_sparse.py $D $P 16 --overrides $OV \
    --emergence 2023-06-06 --emergence-jitter 3 --tag ${FR}${TAG} | grep -E "pinned|scene:|total"
  SRC=twin_work/${FR}_soilfix
  for f in soil_albedo.bin leaf_overrides.txt; do cp $SRC/$f twin_work/${FR}${TAG}/; done
done
echo "=== rate refit done ==="
