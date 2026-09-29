#!/bin/bash -l
#SBATCH --account=publicgrp
#SBATCH --partition=low
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=32
#SBATCH --mem=64G
#SBATCH -J twin_growth
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_growth-%j.out
# Completes the single-genotype time series and fits the growth curve. The pinned-age grid used Plot298-MAGIC226 for the
# middle date, so genotype and plot were confounded with age; this adds 06-27 Plot286-MAGIC083 on the same grid, then
# fits one emergence date and one phyllochron against all three Plot286 dates at once.
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
export TWIN_WORKERS=$SLURM_CPUS_PER_TASK
export TWIN_BINARY=$PWD/build-cpu2/SyntheticAutotuning
EMERGENCE=2023-06-08
for PHY in 2.7 2.0 1.5 1.0; do
  for BB in 0.25 0.5 0.8; do
    OV=twin_work/pa_${PHY}_${BB}_ov.json
    echo "=== phyllochron $PHY  bud_break $BB  2023-06-27_Plot286-MAGIC083 ==="
    env/bin/python scripts/twin_fit_sparse.py 2023-06-27 Plot286-MAGIC083 16 --overrides $OV --emergence $EMERGENCE \
      --tag 2023-06-27_Plot286-MAGIC083_pa${PHY}_${BB} | grep -E "pinned|scene:|total"
  done
done
echo "=== time series complete, fitting the growth curve ==="
env/bin/python scripts/twin_growth_curve.py --workers 16
echo "=== growth jobs done ==="
