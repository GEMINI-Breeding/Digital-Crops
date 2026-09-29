#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH -J twin_rsize
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_rsize-%j.out
# The size-corrected refit (_size workdirs: leaf scale and petiole length pinned to the hand labels, ages and
# positions refitted) rendered for all five frames into twin_work/<frame>_size/render_soil. Each frame's ov.json
# is its _soilfix render overrides with the two labelled parameters replaced, so only geometry differs from the
# published twin. One job, frames in sequence: twin_render_many.sh rebuilds first, and concurrent jobs would race
# on the same build directory. usage: sbatch twin_render_size.sh
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
SUFFIX=${1:-_size}
FRAMES="2023-06-20_Plot286-MAGIC083 2023-06-20_Plot201-MAGIC262 2023-06-27_Plot286-MAGIC083 2023-06-27_Plot298-MAGIC226 2023-07-03_Plot286-MAGIC083"
SUFFIX=$SUFFIX env/bin/python - <<'PY'
import json, os
SUFFIX = os.environ.get("SUFFIX", "_size")
FRAMES = "2023-06-20_Plot286-MAGIC083 2023-06-20_Plot201-MAGIC262 2023-06-27_Plot286-MAGIC083 2023-06-27_Plot298-MAGIC226 2023-07-03_Plot286-MAGIC083".split()
SIZE = {"leaf.petiole_length_min": 0.0845, "leaf.petiole_length_max": 0.1127,
        "leaf.prototype_scale_min": 0.0783, "leaf.prototype_scale_max": 0.1043}
for fr in FRAMES:
    ov = json.load(open(f"twin_work/{fr}_soilfix/ov.json"))
    ov.update(SIZE)
    json.dump(ov, open(f"twin_work/{fr}{SUFFIX}/ov.json", "w"), indent=1)
    print(fr, "ov.json written")
PY
for FR in $FRAMES; do
  W=$PWD/twin_work/${FR}${SUFFIX}
  bash scripts/twin_render_many.sh $W/ov.json $W
done
echo "=== all frames done ==="
