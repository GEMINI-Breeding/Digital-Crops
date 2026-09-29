#!/bin/bash -l
#SBATCH --account=publicgrp
#SBATCH --partition=low
#SBATCH --time=10:00:00
#SBATCH --cpus-per-task=32
#SBATCH --mem=64G
#SBATCH -J twin_shapeopt
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_shapeopt-%j.out
# usage: sbatch scripts/twin_shape_opt_cpu.sh [args for twin_shape_opt.py]
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
export TWIN_WORKERS=$SLURM_CPUS_PER_TASK
export TWIN_BINARY=/group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/build-cpu2/SyntheticAutotuning
echo "=== node $(hostname) cpus $SLURM_CPUS_PER_TASK ==="
env/bin/python scripts/twin_shape_opt.py "$@"
