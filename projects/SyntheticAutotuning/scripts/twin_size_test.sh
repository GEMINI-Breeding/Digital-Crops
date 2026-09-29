#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=01:30:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH -J twin_size
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_size-%j.out
# Leaflet-size / petiole-length test against the hand labels (twin_work/labels): the fitted 06-20 Plot286 layout
# re-rendered with the petiole correction alone, the leaf-size correction alone, and both. Each variant's workdir
# holds its own ov.json and symlinks the fitted layout, soil albedo map and leaf optics from _soilfix, so only the
# two parameters under test differ. usage: sbatch twin_size_test.sh
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh; unset DISPLAY
FR=2023-06-20_Plot286-MAGIC083
for V in petiole leafsize both; do
  bash scripts/twin_render_many.sh $PWD/twin_work/${FR}_size_${V}/ov.json $PWD/twin_work/${FR}_size_${V}
done
echo "=== all variants done ==="
