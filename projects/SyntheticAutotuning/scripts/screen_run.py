"""Execute the Morris design: run the rasterized geometry pass per row and collect the outputs."""
import json, os, subprocess, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real.screen import sample, to_overrides, PROBLEM, OUTPUTS, REAL, analyze
from syn2real.geom_io import read_boxes, nn_spacing
from syn2real.tile import REAL_MIN_BOX_PX

TRAJ = int(os.environ.get("SCREEN_TRAJECTORIES", "8"))
SEED = int(os.environ.get("SCREEN_SEED", "0"))
OUT = "geom_screen"

X = sample(trajectories=TRAJ, seed=SEED)
print(f"Morris design: {len(X)} runs over {PROBLEM['num_vars']} parameters", flush=True)

Y = {k: [] for k in OUTPUTS}
failures = []
for i, row in enumerate(X):
    tag = f"run{i:04d}"
    ov = to_overrides(row)
    args = ["./SyntheticAutotuning", "geom", "../config/baseline.cfg", str(900 + i),
            "leaf.use_obj_mesh", "0", "geom.label_leaves", "1",
            "output.folder", f"../{OUT}/{tag}/"]
    for k, v in ov.items():
        args += [k, v]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        failures.append((i, r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "no stderr"))
    cover = float("nan")
    for tok in r.stdout.split():
        if tok.startswith("veg_cover="):
            cover = float(tok.split("=")[1])
    # Object statistics from the written annotations, filtered as the dataset export filters.
    d = None
    for cand in sorted(os.listdir(f"../{OUT}/{tag}")) if os.path.isdir(f"../{OUT}/{tag}") else []:
        d = os.path.join(f"../{OUT}/{tag}", cand)
    try:
        b = read_boxes(d)
        # Flowers only. Cover requires every leaf to be labelled, which also puts ~1,500 leaf boxes
        # into the annotations; counting those made "boxes per frame" read 1,546 against a real 24
        # and "object size" 163 px against a real 33. The object statistics are about flowers.
        b = b[np.isin(b["name"], ("flower_open", "flower_closed"))]
        b = b[b["size"] >= REAL_MIN_BOX_PX]
    except Exception:
        b = np.empty(0, dtype=[("size", "f4"), ("aspect", "f4"), ("cx", "f4"), ("cy", "f4")])
    Y["cover"].append(cover)
    Y["boxes_per_frame"].append(float(len(b)))
    Y["size_p50"].append(float(np.median(b["size"])) if len(b) else 0.0)
    Y["size_p95"].append(float(np.percentile(b["size"], 95)) if len(b) else 0.0)
    Y["log_aspect_med"].append(float(np.median(np.log(b["aspect"]))) if len(b) else 0.0)
    Y["nn_spacing"].append(nn_spacing(b) if len(b) > 1 else float("nan"))
    os.system(f"rm -rf ../{OUT}/{tag}")
    if (i + 1) % 10 == 0:
        print(f"  {i+1}/{len(X)} runs", flush=True)

# A screen built on failed runs ranks nothing. Report the failures and refuse to analyse if the
# design has been gutted -- the first attempt lost 100 of 104 rows and still printed a table.
if failures:
    print(f"\n{len(failures)} of {len(X)} runs FAILED; first few:", flush=True)
    for i, msg in failures[:5]:
        print(f"   run {i}: {msg}", flush=True)
if len(failures) > 0.1 * len(X):
    raise SystemExit(f"ABORT: {len(failures)}/{len(X)} runs failed, the design is not usable")

print("\n=== Morris elementary effects (mu*, higher = more influential) ===")
for out in OUTPUTS:
    y = np.array(Y[out], dtype=float)
    if not np.isfinite(y).all():
        m = np.nanmean(y[np.isfinite(y)]) if np.isfinite(y).any() else 0.0
        y = np.where(np.isfinite(y), y, m)
    rows = analyze(X, y, out)
    scale = abs(REAL.get(out, 1.0)) or 1.0
    print(f"\n{out}   (real {REAL.get(out)}, mu* shown as fraction of it)")
    for name, mu, sig in rows[:6]:
        print(f"   {name:38s} mu* {mu/scale:7.3f}   sigma {sig/scale:7.3f}")
# Saved AFTER the analysis is printed, and to an absolute path. The first attempt did neither:
# it ran all 104 rows, then died writing a relative path from the wrong working directory, and
# because the save came first the results were never printed either. The raw rows go to stdout as
# well, so the run survives a failure of the write.
print("\n=== raw design and responses ===")
for i, row in enumerate(X):
    print("ROW " + " ".join(f"{v:.5f}" for v in row) + " | " + " ".join(f"{Y[k][i]:.5f}" for k in OUTPUTS), flush=True)
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(PROJ, "audit", "screen.json"), "w") as fh:
    json.dump({"X": X.tolist(), "Y": Y, "names": PROBLEM["names"], "outputs": OUTPUTS}, fh)
print("\nSCREEN COMPLETE")
