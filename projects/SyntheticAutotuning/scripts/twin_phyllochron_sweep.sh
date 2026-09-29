#!/bin/bash -l
#SBATCH --account=publicgrp
#SBATCH --partition=low
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=32
#SBATCH --mem=64G
#SBATCH -J twin_phy
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_phy-%j.out
# Does leaf NUMBER close the gap the hand labels opened? With leaf scale and petiole length pinned to the labels,
# the size-corrected refit lost silhouette IoU on every frame and fell short of real cover on the dense ones, while
# fit ages stayed well below the table ceiling -- so the canopy is too sparse at a matched footprint, not too young.
# Phyllochron sets how fast nodes (and so leaves) appear, so this refits the densest and a mid frame at several
# values with everything else held at the size-corrected overrides. usage: sbatch twin_phyllochron_sweep.sh
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
export TWIN_WORKERS=$SLURM_CPUS_PER_TASK
export TWIN_BINARY=$PWD/build-cpu2/SyntheticAutotuning
for PHY in 2.7 2.2 1.8 1.4; do
  OV=twin_work/phy_${PHY}_ov.json
  env/bin/python -c "
import json
ov = json.load(open('twin_work/size_refit_ov.json')); ov['canopy.phyllochron'] = $PHY
json.dump(ov, open('$OV', 'w'), indent=1)"
  for FR in 2023-07-03_Plot286-MAGIC083 2023-06-27_Plot298-MAGIC226; do
    D=${FR%%_*}; P=${FR#*_}
    echo "=== phyllochron $PHY  $FR ==="
    env/bin/python scripts/twin_fit_sparse.py $D $P 16 --overrides $OV --tag ${FR}_phy${PHY} | grep -E "scene:|total"
  done
done
echo "=== sweep done ==="
