#!/bin/bash -l
#SBATCH --account=publicgrp
#SBATCH --partition=low
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=32
#SBATCH --mem=64G
#SBATCH -J twin_diag
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_diag-%j.out
# Is the per-plant footprint mismatch a search limit, a model limit, or a ceiling? Run on native leaf angles, with the
# Beta(3,1) re-aim dropped: it was flattening the canopy to 32 degrees against a measured 42, which inflates projected
# footprint and would bias every one of these measurements.
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
export TWIN_WORKERS=$SLURM_CPUS_PER_TASK
export TWIN_BINARY=$PWD/build-cpu2/SyntheticAutotuning
env/bin/python scripts/twin_footprint_diagnostics.py --frame 2023-06-27_Plot298-MAGIC226 --suffix _final \
  --overrides twin_work/native_angle_ov.json --seeds 1024 --plants 4 --workers $SLURM_CPUS_PER_TASK
echo "=== diagnostics done ==="
