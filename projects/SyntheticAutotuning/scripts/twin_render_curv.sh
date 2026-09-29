#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH -J twin_curv
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_curv-%j.out
# Two candidates for the setting BB judged to lie between the library's one rate and the tuned splits:
# blade 0.20 against the library's petiole rate, with petiole curvature raised from the library's
# -200..-50 deg/m. Curvature is in it because it is the one knob that moves both measures the same way --
# a bowed petiole projects shorter and lays its blade nearer the stem, so it hides stalk without needing an
# early blade to cover it. Rendered from the _final layouts, so only the geometry differs.
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
for FR in 2023-06-20_Plot286-MAGIC083 2023-06-27_Plot298-MAGIC226; do
  for TAG in _c400 _c800; do
    W=$PWD/twin_work/${FR}${TAG}
    echo "=== $W ==="
    bash scripts/twin_render_many.sh $W/ov.json $W
  done
done
echo "=== all variants done ==="
