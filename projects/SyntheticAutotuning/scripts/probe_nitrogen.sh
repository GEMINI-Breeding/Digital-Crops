#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=120G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_nprobe
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/nprobe-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
unset DISPLAY
env/bin/python - <<'PY'
import json, subprocess
BASE = json.load(open("audit/phase5_confirm.json"))["results"]["18"]["overrides"]
ov = dict(BASE)
for supply, target, rate in [("1.0", "3.0", "0.10"), ("8.0", "3.0", "0.10"),
                            ("8.0", "3.0", "0.20"), ("8.0", "4.2", "0.20")]:
    o = dict(ov)
    o.update({"leaf.nitrogen_model": "1", "leaf.target_N_area": target,
              "leaf.nitrogen_supply_gN": supply, "leaf.max_N_accumulation_rate": rate})
    flat = [x for kv in o.items() for x in kv]
    r = subprocess.run(["./SyntheticAutotuning", "geom", "../config/baseline.cfg", "5200",
                        "leaf.use_obj_mesh", "0", "output.folder", "../nprobe/"] + flat,
                       capture_output=True, text=True, cwd="build-gpu")
    print(f"--- supply {supply}  target {target}  rate {rate}  (rc {r.returncode})", flush=True)
    for line in (r.stdout + r.stderr).splitlines():
        if "DIAG nitrogen" in line or "DIAG leafN" in line or "ERROR" in line:
            print("   " + line.strip(), flush=True)
PY
rm -rf nprobe
echo "PROBE COMPLETE"
