#!/bin/bash -l
#SBATCH --account=publicgrp
#SBATCH --partition=low
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=32
#SBATCH --mem=64G
#SBATCH -J twin_fit
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_fit-%j.out

# CPU-only single-image fit on the raster proxy: usage  sbatch scripts/twin_fit_cpu.sh <date> <plot> [n_seeds] [--overrides f.json] [--tag t]
# The login node is shared (load ~90) and the candidate sweep is embarrassingly parallel, so it
# belongs on a compute node. The binary is the login-node (Vulkan) build: the raster mode needs
# no GPU and no display.
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
export TWIN_WORKERS=$SLURM_CPUS_PER_TASK
export TWIN_BINARY=${TWIN_BINARY_OVERRIDE:-/group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/build-cpu/SyntheticAutotuning}
echo "=== node $(hostname) cpus $SLURM_CPUS_PER_TASK ==="
env/bin/python scripts/twin_fit_sparse.py "$@"
