#!/bin/bash -l
#SBATCH --account=publicgrp
#SBATCH --partition=low
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=32
#SBATCH --mem=64G
#SBATCH -J twin_ident
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_ident-%j.out
# usage: sbatch scripts/twin_ident_cpu.sh <layout> [args for twin_identifiability.py]
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
export TWIN_WORKERS=$SLURM_CPUS_PER_TASK
export TWIN_BINARY=/group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/build-cpu/SyntheticAutotuning
echo "=== node $(hostname) cpus $SLURM_CPUS_PER_TASK ==="
env/bin/python scripts/twin_identifiability.py "$@" --workers $SLURM_CPUS_PER_TASK
