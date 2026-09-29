#!/bin/bash -l
#SBATCH --account=publicgrp
#SBATCH --partition=low
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=32
#SBATCH --mem=64G
#SBATCH -J twin_refit
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_refit-%j.out
# Refit several frames under one set of generator overrides, into twin_work/<frame><suffix>, and carry each frame's soil
# albedo map and leaf optics over from its _leaf fit so the renders differ only in geometry.
# usage: sbatch scripts/twin_refit_many_cpu.sh <overrides.json> <suffix> <frame> [<frame> ...]     (frame = date_plot)
set -e
OV=$1; SUFFIX=$2; shift 2
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
export TWIN_WORKERS=$SLURM_CPUS_PER_TASK
export TWIN_BINARY=${TWIN_BINARY_OVERRIDE:-/group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/build-cpu2/SyntheticAutotuning}
echo "=== node $(hostname) cpus $SLURM_CPUS_PER_TASK binary $TWIN_BINARY ==="
for FR in "$@"; do
  D=${FR%%_*}; P=${FR#*_}
  echo "=== $FR ==="
  env/bin/python scripts/twin_fit_sparse.py $D $P 16 --overrides $OV --tag ${FR}${SUFFIX} | grep -E "stage|scene:|total"
  # Appearance carried over from the newest fit that has it: _soilfix holds the per-frame leaf colour with its
  # leaf-to-leaf variation, while _leaf still has the first uniform-colour fit. Copying the stale one silently
  # rendered a refit with different leaf optics from the twin it was being compared against.
  SRC=twin_work/${FR}_soilfix; [ -f $SRC/leaf_overrides.txt ] || SRC=twin_work/${FR}_leaf
  for f in soil_albedo.bin leaf_overrides.txt; do cp $SRC/$f twin_work/${FR}${SUFFIX}/; done
done
echo "=== done ==="
