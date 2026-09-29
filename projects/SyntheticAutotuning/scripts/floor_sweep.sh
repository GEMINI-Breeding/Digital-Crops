#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=00:40:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=120G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_floor
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/floor-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
unset DISPLAY
env/bin/python - <<'PY'
import json, re, subprocess
import numpy as np
BASE = json.load(open("audit/phase5_confirm.json"))["results"]["18"]["overrides"]
# Real leaf patches sit at hue 123 deg, which the Cab->hue mapping puts at Cab 50+. Sweep the floor
# across the range that spans "clearly too yellow" to "as green as real".
print(f"{'floor N':>8} {'floor Cab':>10} {'Cab p10':>8} {'Cab p50':>8} {'Cab p90':>8} {'spread':>7} {'raised':>14}")
for floor in (0.8, 1.5, 2.0, 2.5, 3.0):
    ov = dict(BASE)
    ov.update({"leaf.nitrogen_model": "1", "leaf.target_N_area": "3.4",
               "leaf.max_N_accumulation_rate": "0.14", "leaf.nitrogen_supply_gN": "8.0",
               "leaf.minimum_N_area": f"{floor:.3f}"})
    args = ["./SyntheticAutotuning", "geom", "../config/baseline.cfg", "5200",
            "leaf.use_obj_mesh", "0", "output.folder", "../floorsweep/"]
    for k, v in ov.items(): args += [k, v]
    r = subprocess.run(args, capture_output=True, text=True, cwd="build-gpu")
    subprocess.run(["rm", "-rf", "floorsweep"])
    if r.returncode != 0:
        raise SystemExit(f"geom failed at floor {floor}: {(r.stderr.strip().splitlines() or ['?'])[-1]}")
    line = next(l for l in r.stdout.splitlines() if "DIAG leafN" in l)
    fl = next((l for l in r.stdout.splitlines() if "DIAG nitrogen_floor" in l), "")
    raised = re.search(r"primitives_raised=(\d+)", fl)
    f = {k: float(v) for k, v in re.findall(r"(Cab_p\d+|Cab_spread)=([-\d.eE+]+)", line)}
    # If the clamp raised nothing at a floor above the reported p10, the clamp is not reaching the
    # data the spectra are built from -- which is exactly how the first version of this sweep
    # reported three identical rows.
    if raised and int(raised.group(1)) == 0 and floor * 20 > f["Cab_p10"]:
        raise SystemExit(f"floor {floor} (Cab {floor*20:.0f}) raised no leaf although p10 is "
                         f"{f['Cab_p10']:.1f} -- the clamp is not reaching the leaf data")
    print(f"{floor:8.1f} {floor*20:10.0f} {f['Cab_p10']:8.1f} {f['Cab_p50']:8.1f} "
          f"{f['Cab_p90']:8.1f} {f['Cab_spread']:7.1f}  raised {raised.group(1) if raised else '?':>7}",
          flush=True)
print("\nreal leaves sit at Cab 50-65 (hue 125) to 65-90 (hue 130); real median hue 123.5")
print("FLOOR SWEEP COMPLETE")
PY
