#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=12:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=220G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_proxyval
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/proxyval-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
unset DISPLAY
cmake -S . -B build-gpu -DCMAKE_BUILD_TYPE=Release > /dev/null
make -C build-gpu -j8 2>&1 | grep -E " error|Error 1" || true
rm -rf frames_val
cd build-gpu
# Eight configurations drawn from the Morris design, spanning the geometric proxy from 0.24 to 5.10.
# These are diverse by construction rather than sequential, which is the whole point: the five
# dataset versions improved monotonically on almost every statistic, so any metric correlated with
# mAP across them and none of them could discriminate between proxies.
while IFS='|' read -r NAME OV; do
  for SEED in 801 802 803 804 805 806; do
    ./SyntheticAutotuning render ../config/baseline.cfg $SEED camera.samples 50 \
        output.folder ../frames_val/$NAME/ $OV 2>&1 \
      | grep -oE "wrote .*" || true
  done
  echo "RENDERED $NAME"
done < ../audit/validation_cmds.txt
echo "PROXYVAL RENDER COMPLETE"
