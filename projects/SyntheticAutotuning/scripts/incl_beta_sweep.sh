#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=120G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_beta
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/beta-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
unset DISPLAY
env/bin/python - <<'PY'
import json, re, subprocess
BASE = json.load(open("audit/phase5_confirm.json"))["results"]["18"]["overrides"]
# The Beta convention is not assumed: each pair is run and the resulting mean inclination read back.
PAIRS = [(None,None),(2.770,1.172),(1.172,2.770),(1.101,1.930),(1.0,1.0),(3.0,1.0),(4.0,1.0)]
print(f"{'mu':>7} {'nu':>7} {'mean deg':>9} {'cos(mean)':>10} {'vs 48.0 deg':>12}")
for mu, nu in PAIRS:
    ov = dict(BASE)
    ov.update({"leaf.prototype_scale_min":"0.1837","leaf.prototype_scale_max":"0.3311",
               "canopy.germination_fraction_min":"0.30","canopy.germination_fraction_max":"0.75"})
    if mu is not None:
        ov.update({"leaf.set_angle_distribution":"1","leaf.angle_beta_mu":f"{mu:.4f}",
                   "leaf.angle_beta_nu":f"{nu:.4f}"})
    args = ["./SyntheticAutotuning","geom","../config/baseline.cfg","9700",
            "leaf.use_obj_mesh","0","geom.label_leaves","1","output.folder","../betaprobe/"]
    for k,v in ov.items(): args += [k,v]
    r = subprocess.run(args, capture_output=True, text=True, cwd="build-gpu")
    subprocess.run(["rm","-rf","betaprobe"])
    if r.returncode != 0:
        print(f"{str(mu):>7} {str(nu):>7}   FAILED: {(r.stderr.strip().splitlines() or ['?'])[-1][:60]}")
        continue
    line = next((l for l in r.stdout.splitlines() if "DIAG leaf_inclination" in l), "")
    m = re.search(r"mean_deg=([\d.]+).*projection_factor=([\d.]+)", line)
    if not m:
        print(f"{str(mu):>7} {str(nu):>7}   no DIAG line"); continue
    mean, proj = float(m.group(1)), float(m.group(2))
    print(f"{str(mu):>7} {str(nu):>7} {mean:9.1f} {proj:10.3f} {proj/0.6686:12.2f}x", flush=True)
print("\ntarget: planophile cowpea, mean inclination ~30 deg (projection 0.87, i.e. 1.29x on 48 deg)")
print("BETA SWEEP COMPLETE")
PY
