"""Find the leaf scale that puts canopy structure radius on the real value.

The granulometry calibration in geom_io was fitted between a PROCEDURAL-leaf rasterized pass and an
OBJ-mesh render, which is the mismatch section 12 documents as having broken the cover calibration.
Its rank correlation of +0.90 still makes it a sound screening device, but the absolute offset is
suspect, so this sweep runs the rasterized pass with the SAME scanned meshes the render uses and the
chosen value is confirmed by an actual render afterwards.

Side effects are reported alongside because leaf size does not move alone: widening it once already
fixed structure radius and overshot canopy cover, which is how the cover calibration went wrong.
"""
import json, os, re, subprocess, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real.geom_io import granulometry_from_render, calibrated_mean_radius

BASE = json.load(open("audit/phase5_confirm.json"))["results"]["18"]["overrides"]
WIDTH = float(BASE["leaf.prototype_scale_max"]) - float(BASE["leaf.prototype_scale_min"])
MINS = [0.094, 0.110, 0.125, 0.140, 0.155, 0.170]
SEEDS = (5200, 5201)
REAL_MEAN_R = 38.7
OUT = "audit/leaf_scale_sweep.json"

print(f"trial 18 leaf scale {BASE['leaf.prototype_scale_min']}-{BASE['leaf.prototype_scale_max']} "
      f"(width {WIDTH:.4f}, held constant)\n", flush=True)
print(f"{'scale':>14} {'raw mean_r':>11} {'calibrated':>11} {'cover':>7} {'flowers':>8}", flush=True)

rows = []
for lo in MINS:
    hi = lo + WIDTH
    per_seed = []
    for seed in SEEDS:
        tag = f"lss_{lo:.3f}_{seed}"
        os.system(f"rm -rf {tag}")
        ov = dict(BASE)
        ov["leaf.prototype_scale_min"] = f"{lo:.4f}"
        ov["leaf.prototype_scale_max"] = f"{hi:.4f}"
        args = ["./SyntheticAutotuning", "geom", "../config/baseline.cfg", str(seed),
                "leaf.use_obj_mesh", "1",           # match the render; NOT the procedural default
                "geom.label_leaves", "1", "geom.write_rgb", "1",
                "output.folder", f"../{tag}/"]
        for k, v in ov.items():
            args += [k, v]
        r = subprocess.run(args, capture_output=True, text=True, cwd="build-gpu")
        if r.returncode != 0:
            raise SystemExit(f"geom failed at {lo:.3f}: {(r.stderr.strip().splitlines() or ['?'])[-1]}")
        cover = next((float(t.split("=")[1]) for t in r.stdout.split() if t.startswith("veg_cover=")), np.nan)
        flowers = sum(int(m) for m in re.findall(r"flowers_(?:open|closed)=(\d+)", r.stdout))
        runs = sorted(os.listdir(tag))
        _peak, mean_r, _ = granulometry_from_render(os.path.join(tag, runs[-1]))
        os.system(f"rm -rf {tag}")
        per_seed.append((mean_r, cover, flowers))
    raw = float(np.mean([p[0] for p in per_seed]))
    cov = float(np.mean([p[1] for p in per_seed]))
    fl = float(np.mean([p[2] for p in per_seed]))
    cal = calibrated_mean_radius(raw)
    rows.append(dict(scale_min=lo, scale_max=hi, raw_mean_r=raw, calibrated_mean_r=cal,
                     cover=cov, flowers=fl))
    print(f"{lo:.3f}-{hi:.3f} {raw:11.2f} {cal:11.2f} {cov:7.3f} {fl:8.0f}", flush=True)

json.dump(dict(real_mean_r=REAL_MEAN_R, real_cover_p50=0.947, rows=rows), open(OUT, "w"), indent=1)
best = min(rows, key=lambda r: abs(r["calibrated_mean_r"] - REAL_MEAN_R))
print(f"\nreal structure radius {REAL_MEAN_R}, real cover p50 0.947")
print(f"closest: leaf scale {best['scale_min']:.3f}-{best['scale_max']:.3f}  "
      f"calibrated mean_r {best['calibrated_mean_r']:.2f}  cover {best['cover']:.3f}")
print(f"\nwrote {OUT}")
print("LEAF SCALE SWEEP COMPLETE")
