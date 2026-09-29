"""Stage 1 on a sparse frame: which generator parameters let a seedling be matched at all?

For a handful of the largest real plants, every combination of leaf scale, phyllochron and
petiole length is given a reduced per-plant fit (a few seeds x yaws at the footprint-matched
age) and the best IoU per plant is recorded. The parameter set that maximises the mean best IoU
is what stage 3 should run with; the age table is rebuilt per combination because it changes
with all three parameters.

usage: twin_stage1_screen.py <date> [plot] [--plants 3] [--seeds 6] [--yaws 8] [--workers N] [--tag name]
"""
import argparse
import itertools
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import twin.fit as F  # noqa: E402
import twin.raster as TR  # noqa: E402
import twin.real as R  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("date"); ap.add_argument("plot", nargs="?", default="Plot286-MAGIC083")
ap.add_argument("--plants", type=int, default=3); ap.add_argument("--seeds", type=int, default=6); ap.add_argument("--yaws", type=int, default=8)
ap.add_argument("--workers", type=int, default=int(os.environ.get("TWIN_WORKERS", "6"))); ap.add_argument("--tag", default=None)
a = ap.parse_args()

GRID = {
    "leaf.prototype_scale": [(0.05, 0.07), (0.07, 0.10), (0.10, 0.16)],
    "canopy.phyllochron": [1.0, 1.5, 2.0],
    "leaf.petiole_length": [(0.04, 0.07), (0.07, 0.11), (0.10, 0.14)],
}
fs = R.frames(a.date, a.plot)
path = fs[len(fs) // 2]
work = os.path.join(TR.PROJECT, "twin_work", a.tag or f"{a.date}_{a.plot}_stage1")
os.makedirs(work, exist_ok=True)
log = open(os.path.join(work, "screen.log"), "a")
def say(*x):
    s = " ".join(str(v) for v in x); print(s, flush=True); log.write(s + "\n"); log.flush()

target = F.Target(path, work)
plants = sorted(target.plants(min_area_px=3000, min_sep_px=120), key=lambda p: -p["area_px"])[:a.plants]
say(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} {path}: {len(plants)} plants, areas {[int(p['area_px']) for p in plants]}")
sc = F.px_scale(F.BASE)
veg_s, valid_s, labels_s = target.downsampled(sc)
H, W = veg_s.shape
ages = (6, 8, 10, 12, 14, 16, 18, 20, 23, 26, 30)
results = []
rng = np.random.RandomState(0)
seeds = rng.randint(1, 2**31 - 1, size=a.seeds)
yaws = np.arange(0, 360, 360 / a.yaws)
for combo in itertools.product(*GRID.values()):
    (ls_lo, ls_hi), phyllo, (pl_lo, pl_hi) = combo
    ov = dict(F.BASE)
    ov.update({"leaf.prototype_scale_min": ls_lo, "leaf.prototype_scale_max": ls_hi, "canopy.phyllochron": phyllo,
               "leaf.petiole_length_min": pl_lo, "leaf.petiole_length_max": pl_hi})
    cdir = os.path.join(work, "cand")
    t0 = time.time()
    table = F.footprint_table(ov, ages, (1, 2, 3), os.path.join(work, "table"))
    best_ious = []
    for c in plants:
        age = F.invert_footprint(table, c["area_px"] * sc * sc)
        bx, by = R.ground_xy(c["x"], c["y"], camera_height_m=ov["camera.height"])
        real_mask = labels_s == c["label"]
        r = int(np.sqrt(real_mask.sum() / np.pi))
        import cv2
        region = cv2.dilate(real_mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))) > 0
        jobs = [(age, int(s), bx, by, float(y), cdir, f"s{c['label']}_{s}_{int(y)}") for s in seeds for y in yaws]
        res = F.candidates(ov, jobs, a.workers)
        best = max(F.score_candidate(F.place(veg, x0, y0, W, H), real_mask, region) for (veg, x0, y0) in res)
        best_ious.append(best)
    row = dict(leaf_scale=(ls_lo, ls_hi), phyllochron=phyllo, petiole=(pl_lo, pl_hi), best_iou=best_ious, mean=float(np.mean(best_ious)), seconds=time.time() - t0)
    results.append(row)
    say(f"leaf {ls_lo:.2f}-{ls_hi:.2f} phyllo {phyllo:.1f} petiole {pl_lo:.2f}-{pl_hi:.2f}: best IoU {np.round(best_ious, 3)} mean {row['mean']:.3f} ({row['seconds']:.0f} s)")
    json.dump(results, open(os.path.join(work, "screen.json"), "w"), indent=1)
results.sort(key=lambda r: -r["mean"])
say("BEST:", json.dumps(results[0]))
