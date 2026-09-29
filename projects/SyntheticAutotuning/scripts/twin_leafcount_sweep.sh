#!/bin/bash -l
#SBATCH --account=publicgrp
#SBATCH --partition=low
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=32
#SBATCH --mem=64G
#SBATCH -J twin_leafcount
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_leafcount-%j.out
# Leaf production against the cover deficit. With leaf scale and petiole length pinned to the hand labels and the yaw
# rotation fixed, cover matches real on the young frames and falls 10-16 % short on the older ones -- a shortfall that
# compounds with development, so it belongs to how fast the plant makes leaves. Two parameters do that: phyllochron
# (nodes per day on a shoot) and vegetative bud break (how readily lateral shoots start). Each combination is refitted,
# so plant ages and positions adapt to it rather than the grid being scored on someone else's layout.
# usage: sbatch twin_leafcount_sweep.sh
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
export TWIN_WORKERS=$SLURM_CPUS_PER_TASK
export TWIN_BINARY=$PWD/build-cpu2/SyntheticAutotuning
for PHY in 2.7 2.0 1.5; do
  for BB in 0.25 0.5 0.8; do
    OV=twin_work/lc_${PHY}_${BB}_ov.json
    env/bin/python -c "
import json
ov = json.load(open('twin_work/size_refit_ov.json'))
ov['canopy.phyllochron'] = $PHY
ov['canopy.bud_break_probability'] = $BB
json.dump(ov, open('$OV', 'w'), indent=1)"
    for FR in 2023-07-03_Plot286-MAGIC083 2023-06-27_Plot298-MAGIC226; do
      D=${FR%%_*}; P=${FR#*_}
      echo "=== phyllochron $PHY  bud_break $BB  $FR ==="
      env/bin/python scripts/twin_fit_sparse.py $D $P 16 --overrides $OV --tag ${FR}_lc${PHY}_${BB} | grep -E "scene:|total"
    done
  done
done
echo "=== sweep done ==="
