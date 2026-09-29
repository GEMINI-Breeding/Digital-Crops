#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH -J helios_treetest
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/helios_treetest-%j.out
# Radiation tests from a given Helios tree on a GPU node.
# usage: sbatch helios_tree_test.sh <helios_root> <label> [extra run_tests args]
set -e
ROOT=$1; shift
LABEL=$1; shift
LOG=/group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/helios_treetest_${LABEL}.log
source /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/scripts/env.sh
export VULKAN_SDK=/group/bnbaileygrp/bnbailey/vulkan-sdk/1.3.290.0/x86_64
unset DISPLAY
echo "=== $LABEL from $ROOT on $(hostname) ==="; nvidia-smi --query-gpu=name,driver_version --format=csv,noheader
cd $ROOT/utilities
./run_tests.sh --test radiation --project-dir $ROOT/utilities/.scratch/tree_${LABEL} --verbose "$@" > $LOG 2>&1 || echo "run_tests exit=$?"
tail -60 $LOG
echo "=== done ==="
