#!/bin/bash -l
# Best twin (geometry _fixD, scanned leaves, fitted leaf colour) re-rendered with a per-frame soil albedo scale, into
# twin_work/<frame>_soilfix/render_soil. twin/soil.py normalizes the albedo map's median to an assumed 0.04, which left the
# rendered soil ~10 L* dark against real at the exposure that matches real foliage; each frame's ov.json carries its scale.
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
for FR in 2023-06-20_Plot286-MAGIC083 2023-06-20_Plot201-MAGIC262 2023-06-27_Plot286-MAGIC083 2023-06-27_Plot298-MAGIC226 2023-07-03_Plot286-MAGIC083; do
  W=$PWD/twin_work/${FR}_soilfix
  bash scripts/twin_render_many.sh $W/ov.json $W
done
