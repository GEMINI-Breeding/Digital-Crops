#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=12:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=220G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_size
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/size-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
unset DISPLAY
cmake -S . -B build-gpu -DCMAKE_BUILD_TYPE=Release > /dev/null
make -C build-gpu -j8 2>&1 | grep -E " error|Error 1" || true
rm -rf frames_size frames_cfg1x
cd build-gpu
# (1) Object-size sweep: only flower.prototype_scale varies, from the cfg1 base. Tests whether
# synthetic objects want to be LARGER than real -- cfg1 uses 0.045 against a real-matching 0.030
# and outscores every calibrated version.
while IFS='|' read -r NAME OV; do
  for SEED in 901 902 903 904; do
    ./SyntheticAutotuning render ../config/baseline.cfg $SEED camera.samples 50 \
        output.folder ../frames_size/$NAME/ $OV 2>&1 | grep -oE "wrote .*" || true
  done
  echo "RENDERED $NAME"
done < ../audit/size_sweep_cmds.txt
# (2) cfg1 confirmation at twice the frames, to check 0.398 was not a lucky draw.
OV=$(cat ../audit/cfg1_overrides.txt)
for SEED in 811 812 813 814 815 816 817 818 819 820 821 822; do
  ./SyntheticAutotuning render ../config/baseline.cfg $SEED camera.samples 50 \
      output.folder ../frames_cfg1x/ $OV 2>&1 | grep -oE "wrote .*" || true
done
echo "RENDERED cfg1x"
echo "SIZE SWEEP COMPLETE"
