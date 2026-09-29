#!/bin/bash -l
#SBATCH --account=publicgrp
#SBATCH --partition=low
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=32
#SBATCH --mem=64G
#SBATCH -J twin_shape
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_shape-%j.out
# Petiole length against petiole pitch, scored on where the blades actually sit. The radial profile shows the twin
# carrying about 40 % too much leaf area in its outer quarter and 15 % too little inside -- blades too far from the
# stem. Petiole length was scaled 1.41x from PROJECTED label measurements, which conflate true length with the angle
# the petiole is held at, so the two are swept together here: a flatter petiole and a shorter one both move a blade
# outward in a nadir view, and only their combination is identifiable from the image. Added droop is held at zero,
# since the cowpea library already draws petiole.curvature from (-200, -50) and a flexibility term stacks on top.
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
export TWIN_WORKERS=$SLURM_CPUS_PER_TASK
export TWIN_BINARY=$PWD/build-cpu2/SyntheticAutotuning
env/bin/python scripts/twin_shape_fit.py --frame 2023-06-27_Plot298-MAGIC226 --suffix _final \
  --petiole-scale 0.65,0.8,0.9,1.0,1.1 --pitch-centre 33,41,49,57 \
  --fixed "canopy.insertion_angle_tip=40,canopy.phyllotactic_angle=100,leaf.petiole_flexibility=0" --workers 24
echo "=== shape fit done ==="
