#!/bin/bash -l
#SBATCH --account=publicgrp
#SBATCH --partition=low
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=32
#SBATCH --mem=64G
#SBATCH -J twin_seedbudget
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_seedbudget-%j.out
# usage: sbatch scripts/twin_seed_budget_cpu.sh <date> <plot> --overrides <json> [--seeds 64] [--compare 16] [--tag t]
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
export TWIN_WORKERS=$SLURM_CPUS_PER_TASK
export TWIN_BINARY=/group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/build-cpu/SyntheticAutotuning
echo "=== node $(hostname) cpus $SLURM_CPUS_PER_TASK ==="
env/bin/python scripts/twin_seed_budget.py "$@"
