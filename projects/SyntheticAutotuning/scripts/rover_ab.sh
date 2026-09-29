#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=220G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_rover
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/rover-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
make -C build-gpu -j8 > /dev/null 2>&1
cd build-gpu
for rv in 0 1; do
 for ccm in yes no; do
  cf=../calib/ccm_camA_20230728.xml; [ "$ccm" = no ] && cf=""
  echo "### rover=$rv ccm=$ccm"
  ./SyntheticAutotuning render ../config/baseline.cfg 201 \
    camera.resolution_x 900 camera.resolution_y 712 camera.samples 30 \
    scene.load_rover $rv post.ccm_file "$cf" light.source_scale 1.0 \
    output.folder ../frames_rv_${rv}_${ccm}/ 2>&1 | grep -oE "wrote .*" | tr '\n' ' '
  echo
 done
done
