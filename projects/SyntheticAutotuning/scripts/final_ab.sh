#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_final
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/final-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
make -C build-gpu -j8 > /dev/null 2>&1
cd build-gpu
for tag in wboff_noccm wboff_ccm; do
  ccm=""; [ "$tag" = wboff_ccm ] && ccm=../calib/ccm_camA_20230728.xml
  echo "########## $tag ##########"
  ./SyntheticAutotuning render ../config/baseline.cfg 42 \
    camera.resolution_x 648 camera.resolution_y 512 camera.samples 40 canopy.age 40 \
    post.ccm_file "$ccm" output.folder ../frames_$tag/ 2>&1 | grep -E "wrote|canopy_top"
done
