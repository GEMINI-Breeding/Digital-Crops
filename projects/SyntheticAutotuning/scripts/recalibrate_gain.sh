#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=220G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_gain
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/gain-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
unset DISPLAY
env/bin/python - <<'PY'
import glob, json, os, subprocess, sys
sys.path.insert(0, os.path.abspath("."))
from syn2real import camera_pipeline as cp

# Leaf angle changes how much light foliage catches, so the exposure gain is not transferable
# between canopies with different leaf angle distributions. The planophile canopy rendered 13 L*
# brighter than real at the gain calibrated for the uniform one.
BEST = json.load(open("audit/best_config.json"))["overrides"]
RAW = "gaincal_raw"
os.system(f"rm -rf {RAW}")
flat = [x for kv in BEST.items() for x in kv]
for seed in (9000, 9001, 9002, 9003):
    r = subprocess.run(["./SyntheticAutotuning","render","../config/baseline.cfg",str(seed),
                        "camera.samples","50","output.folder",f"../{RAW}/"]+flat,
                       capture_output=True, text=True, cwd="build-gpu")
    if r.returncode != 0:
        raise SystemExit(f"render failed: {(r.stderr.strip().splitlines() or ['?'])[-1]}")
print(f"rendered 4 frames of the best configuration", flush=True)
# develop.py calibrates the gain itself when --gain is omitted, bisecting on foliage L*.
r = subprocess.run(["env/bin/python","scripts/develop.py",RAW,"--out","gaincal_dev",
                    "--target-L","47.84"], capture_output=True, text=True)
print(r.stdout.strip()[-800:], flush=True)
if r.returncode != 0:
    print(r.stderr.strip()[-600:]); raise SystemExit("develop failed")
os.system(f"rm -rf {RAW} gaincal_dev")
print("GAIN RECALIBRATION COMPLETE")
PY
