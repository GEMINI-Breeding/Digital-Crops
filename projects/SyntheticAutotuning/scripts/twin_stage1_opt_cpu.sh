#!/bin/bash -l
#SBATCH --account=publicgrp
#SBATCH --partition=low
#SBATCH --time=08:00:00
#SBATCH --cpus-per-task=32
#SBATCH --mem=64G
#SBATCH -J twin_s1opt
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_s1opt-%j.out
# usage: sbatch scripts/twin_stage1_opt_cpu.sh <date> [args for twin_stage1_opt.py]
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
export TWIN_WORKERS=$SLURM_CPUS_PER_TASK
export TWIN_BINARY=/group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/build-cpu/SyntheticAutotuning
echo "=== node $(hostname) cpus $SLURM_CPUS_PER_TASK ==="
env/bin/python scripts/twin_stage1_opt.py "$@" --workers $SLURM_CPUS_PER_TASK
