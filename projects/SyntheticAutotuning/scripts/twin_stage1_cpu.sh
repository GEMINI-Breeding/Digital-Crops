#!/bin/bash -l
#SBATCH --account=publicgrp
#SBATCH --partition=low
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=32
#SBATCH --mem=64G
#SBATCH -J twin_stage1
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_stage1-%j.out
# usage: sbatch scripts/twin_stage1_cpu.sh <date> [args]   (uses the build-cpu binary, which has the petiole parameters)
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
export TWIN_WORKERS=$SLURM_CPUS_PER_TASK
export TWIN_BINARY=/group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/build-cpu/SyntheticAutotuning
echo "=== node $(hostname) cpus $SLURM_CPUS_PER_TASK binary $TWIN_BINARY ==="
env/bin/python scripts/twin_stage1_screen.py "$@" --workers $SLURM_CPUS_PER_TASK
