#!/bin/bash -l
#SBATCH --account=publicgrp
#SBATCH --partition=low
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=32
#SBATCH --mem=64G
#SBATCH -J twin_pinned
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_pinned-%j.out
# Leaf production with plant age pinned from outside the fit. Age and leaf production trade through footprint area, so
# the free-age sweep drove phyllochron to the fast edge of its grid (1.5 d/node, botanically implausible) while the fit
# took the plants younger to pay for it. The stand's own emergence date breaks that: five independent free-age fits over
# three imaging dates recovered 2023-06-08 within two days, eight days after the assumed planting -- a cowpea emergence
# lag. Ages are held at (frame date - emergence) here, leaf scale and petiole length stay pinned to the hand labels, and
# only phyllochron and bud break move. The grid reaches down to 1.0 d/node so the optimum is not on an edge again.
# usage: sbatch twin_pinnedage_sweep.sh
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
export TWIN_WORKERS=$SLURM_CPUS_PER_TASK
export TWIN_BINARY=$PWD/build-cpu2/SyntheticAutotuning
EMERGENCE=2023-06-08
for PHY in 2.7 2.0 1.5 1.0; do
  for BB in 0.25 0.5 0.8; do
    OV=twin_work/pa_${PHY}_${BB}_ov.json
    env/bin/python -c "
import json
ov = json.load(open('twin_work/size_refit_ov.json'))
ov['canopy.phyllochron'] = $PHY
ov['canopy.bud_break_probability'] = $BB
json.dump(ov, open('$OV', 'w'), indent=1)"
    for FR in 2023-07-03_Plot286-MAGIC083 2023-06-27_Plot298-MAGIC226 2023-06-20_Plot286-MAGIC083; do
      D=${FR%%_*}; P=${FR#*_}
      echo "=== phyllochron $PHY  bud_break $BB  $FR ==="
      env/bin/python scripts/twin_fit_sparse.py $D $P 16 --overrides $OV --emergence $EMERGENCE --tag ${FR}_pa${PHY}_${BB} | grep -E "pinned|scene:|total"
    done
  done
done
echo "=== sweep done ==="
