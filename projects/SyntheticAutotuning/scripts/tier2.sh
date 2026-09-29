#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=120G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_tier2
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/tier2-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
# No network on the compute nodes: point ultralytics at the cached weights and stop it phoning home.
export YOLO_OFFLINE=1
export ULTRALYTICS_OFFLINE=1
rm -rf tier2_work tier2_runs
export TIER2_SEEDS=6
env/bin/python scripts/tier2_run.py
