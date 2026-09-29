#!/bin/bash -l
#SBATCH --account=publicgrp
#SBATCH --partition=low
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=32
#SBATCH --mem=64G
#SBATCH -J twin_closed
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_closed-%j.out
# usage: sbatch scripts/twin_fit_closed_cpu.sh <date|image> [args passed to twin_fit_closed.py]
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
export TWIN_WORKERS=$SLURM_CPUS_PER_TASK
echo "=== node $(hostname) cpus $SLURM_CPUS_PER_TASK ==="
env/bin/python scripts/twin_fit_closed.py "$@" --workers $SLURM_CPUS_PER_TASK
