#!/bin/bash -l
#SBATCH --account=publicgrp
#SBATCH --partition=low
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=32
#SBATCH --mem=64G
#SBATCH -J twin_pseudo
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_pseudo-%j.out
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
export TWIN_WORKERS=$SLURM_CPUS_PER_TASK
echo "=== node $(hostname) cpus $SLURM_CPUS_PER_TASK ==="
env/bin/python scripts/twin_pseudo_validate.py "$@" --workers $SLURM_CPUS_PER_TASK
