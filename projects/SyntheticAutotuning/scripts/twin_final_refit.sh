#!/bin/bash -l
#SBATCH --account=publicgrp
#SBATCH --partition=low
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=32
#SBATCH --mem=64G
#SBATCH -J twin_final
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_final-%j.out
# The twin at everything established today: leaf scale and petiole length from the hand labels, the per-plant yaw applied
# to objects so plants stay whole, and plant age taken from the stand's own emergence (2023-06-06, fitted jointly across
# the Plot286 time series) rather than from each plant's footprint -- with a few days of jitter so plants still differ in
# vigour. Generator parameters are otherwise the library's: phyllochron 2.7, library branching.
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
export TWIN_WORKERS=$SLURM_CPUS_PER_TASK
export TWIN_BINARY=$PWD/build-cpu2/SyntheticAutotuning
for FR in 2023-06-20_Plot286-MAGIC083 2023-06-20_Plot201-MAGIC262 2023-06-27_Plot286-MAGIC083 2023-06-27_Plot298-MAGIC226 2023-07-03_Plot286-MAGIC083; do
  D=${FR%%_*}; P=${FR#*_}
  echo "=== $FR ==="
  env/bin/python scripts/twin_fit_sparse.py $D $P 16 --overrides twin_work/size_refit_ov.json \
    --emergence 2023-06-06 --emergence-jitter 3 --tag ${FR}_final | grep -E "pinned|scene:|total"
  SRC=twin_work/${FR}_soilfix
  for f in soil_albedo.bin leaf_overrides.txt; do cp $SRC/$f twin_work/${FR}_final/; done
done
echo "=== final refit done ==="
