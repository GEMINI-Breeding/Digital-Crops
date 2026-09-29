#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=120G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_incl
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/incl-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
unset DISPLAY
env/bin/python - <<'PY'
import json, subprocess
BASE = json.load(open("audit/phase5_confirm.json"))["results"]["18"]["overrides"]
# Procedural leaves: inclination is a property of the plant model, not of the leaf mesh, so the
# fast pass measures it correctly and in ~20 s rather than ~30 min.
ov = dict(BASE)
ov.update({"leaf.prototype_scale_min": "0.1837", "leaf.prototype_scale_max": "0.3311",
           "canopy.germination_fraction_min": "0.30", "canopy.germination_fraction_max": "0.75"})
args = ["./SyntheticAutotuning", "geom", "../config/baseline.cfg", "9700",
        "leaf.use_obj_mesh", "0", "geom.label_leaves", "1", "output.folder", "../inclprobe/"]
for k, v in ov.items(): args += [k, v]
r = subprocess.run(args, capture_output=True, text=True, cwd="build-gpu")
subprocess.run(["rm", "-rf", "inclprobe"])
for line in (r.stdout + r.stderr).splitlines():
    if "DIAG leaf_inclination" in line or "ERROR" in line:
        print(line.strip(), flush=True)
print("rc", r.returncode)
print()
print("bins are 0-90 deg in 9 steps of 10 deg; 0 = horizontal (full nadir projection),")
print("90 = vertical (invisible from above). A planophile cowpea canopy should be weighted")
print("toward the low bins; the projection factor is cos(mean inclination).")
print("INCLINATION PROBE COMPLETE")
PY
