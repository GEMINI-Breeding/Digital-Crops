#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH -J twin_rrate
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_rrate-%j.out
# The rate-split refit (_rate workdirs) rendered for all five frames. Each frame's ov.json is the _final render
# overrides with the two rate keys added, so only the blade/petiole timing differs from the published twin.
# One job, frames in sequence: twin_render_many.sh rebuilds first and concurrent jobs would race on the build
# directory.
#   usage: sbatch twin_render_rate.sh <tag> <extra.json>
# <extra.json> holds the generator keys to add to each frame's _final render overrides -- whatever the fit
# used beyond the size-corrected baseline, so that only those keys differ from the published twin.
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
TAG=${1:?usage: twin_render_rate.sh <tag> <extra.json>}
EXTRA=${2:?usage: twin_render_rate.sh <tag> <extra.json>}
export TAG EXTRA
FRAMES="2023-06-20_Plot286-MAGIC083 2023-06-20_Plot201-MAGIC262 2023-06-27_Plot286-MAGIC083 2023-06-27_Plot298-MAGIC226 2023-07-03_Plot286-MAGIC083"
env/bin/python - <<'PY'
import json
FRAMES = "2023-06-20_Plot286-MAGIC083 2023-06-20_Plot201-MAGIC262 2023-06-27_Plot286-MAGIC083 2023-06-27_Plot298-MAGIC226 2023-07-03_Plot286-MAGIC083".split()
import os
TAG = os.environ["TAG"]
EXTRA = json.load(open(os.environ["EXTRA"]))
for fr in FRAMES:
    ov = json.load(open(f"twin_work/{fr}_final/ov.json"))
    ov.update(EXTRA)
    os.makedirs(f"twin_work/{fr}{TAG}", exist_ok=True)
    json.dump(ov, open(f"twin_work/{fr}{TAG}/ov.json", "w"), indent=1)
    print(fr, "ov.json written")
PY
for FR in $FRAMES; do
  W=$PWD/twin_work/${FR}${TAG}
  bash scripts/twin_render_many.sh $W/ov.json $W
done
echo "=== all frames done ==="
