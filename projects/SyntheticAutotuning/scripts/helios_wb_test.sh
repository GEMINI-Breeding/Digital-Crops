#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=01:30:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH -J helios_wbtest
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/helios_wbtest-%j.out
# Radiation white-balance regression test on a GPU node. usage: sbatch helios_wb_test.sh <label> [extra run_tests args]
set -e
LABEL=$1; shift
source /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/scripts/env.sh
export VULKAN_SDK=/group/bnbaileygrp/bnbailey/vulkan-sdk/1.3.290.0/x86_64
unset DISPLAY
echo "=== $LABEL on $(hostname) ==="; nvidia-smi --query-gpu=name --format=csv,noheader
cd /group/bnbaileygrp/bnbailey/Helios/utilities
./run_tests.sh --requiregpu --test radiation --project-dir /group/bnbaileygrp/bnbailey/Helios/utilities/.scratch/wb_proj --verbose "$@" > /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/helios_wbtest_${LABEL}.log 2>&1 || echo "run_tests exit=$?"
tail -40 /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/helios_wbtest_${LABEL}.log
echo "=== done ==="
