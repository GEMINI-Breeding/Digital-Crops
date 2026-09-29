"""How much does a bigger seed search buy? Per-plant IoU against the number of seeds and yaws tried.

Runs the sparse fit's stages 1 and 3 on one frame with a large seed pool, keeping every candidate's IoU, and reads off the
expected best IoU of a smaller search exactly: for K seeds drawn from the pool of N, the best of the K is the j-th best of the
pool with probability C(N-j, K-1) / C(N, K). Then refines (stage 4) twice, from the best of the first `--compare` seeds and from
the best of the whole pool, and scores both scenes, so the gain is measured after refinement too, which is what a fit keeps.

usage: twin_seed_budget.py <date> <plot> --overrides <fit.json or optimiser json> [--seeds 64] [--compare 16] [--tag name]
"""
import argparse
import copy
import json
import os
import sys
import time
from math import comb

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np  # noqa: E402

import twin.fit as F  # noqa: E402
import twin.raster as TR  # noqa: E402
import twin.real as R  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("date"); ap.add_argument("plot")
ap.add_argument("--overrides", required=True)
ap.add_argument("--seeds", type=int, default=64)
ap.add_argument("--compare", type=int, default=16)
ap.add_argument("--tag", default=None)
a = ap.parse_args()
workers = int(os.environ.get("TWIN_WORKERS", "6"))

fs = R.frames(a.date, a.plot)
path = fs[len(fs) // 2]
work = os.path.join(TR.PROJECT, "twin_work", a.tag or f"{a.date}_{a.plot}_seedbudget")
os.makedirs(work, exist_ok=True)
logf = open(os.path.join(work, "seed_budget.log"), "a")


def say(*x):
    s = " ".join(str(v) for v in x)
    print(s, flush=True)
    logf.write(s + "\n")
    logf.flush()


extra = json.load(open(a.overrides))
extra = extra.get("overrides", extra.get("best_overrides", extra))
ov = dict(F.BASE)
ov.update(extra)
say(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} {path}, {a.seeds} seeds, overrides from {a.overrides}")

target = F.Target(path, work)
scores = {}
t0 = time.time()
sites, _ = F.fit_sparse(target, ov, work, n_seeds=a.seeds, refine=False, workers=workers, log=say, scores=scores)
say(f"stages 1+3 with {a.seeds} seeds: {time.time() - t0:.0f} s")


def expected_best(values, k):
    """Expected maximum of k values drawn without replacement from `values`."""
    v = np.sort(np.asarray(values))[::-1]
    n = len(v)
    return float(sum(v[j] * comb(n - 1 - j, k - 1) for j in range(n - k + 1)) / comb(n, k))


iou = [np.array(x) for x in scores["iou"]]  # per site: (seeds, yaws)
n_yaws = iou[0].shape[1]
curve = {}
for yaw_every, label in ((1, f"{n_yaws} yaws"), (2, f"{n_yaws // 2} yaws")):
    rows = []
    for K in (1, 2, 4, 8, 12, 16, 24, 32, 48, a.seeds):
        if K > a.seeds:
            continue
        per_site = [expected_best(m[:, ::yaw_every].max(axis=1), K) for m in iou]
        rows.append(dict(K=K, mean=float(np.mean(per_site)), min=float(np.min(per_site)), max=float(np.max(per_site))))
    curve[label] = rows
    say(f"expected best per-plant IoU before refinement, {label}:")
    for r in rows:
        say(f"  K={r['K']:3d}  mean {r['mean']:.4f}  (sites {r['min']:.3f}-{r['max']:.3f})")

# Refine from the best of the first `compare` seeds and from the best of the whole pool
_, _, labels_s = target.downsampled(F.px_scale(ov))
H, W = labels_s.shape
ages = (6, 8, 10, 12, 14, 16, 18, 20, 23, 26, 30, 35, 40, 46)
yaws = scores["yaws"]
results = {}
for name, k in ((f"best of {a.compare}", a.compare), (f"best of {a.seeds}", a.seeds)):
    chosen = copy.deepcopy(sites)
    for s, m, seeds in zip(chosen, iou, scores["seeds"]):
        sub = m[:k]
        i, j = np.unravel_index(int(np.argmax(sub)), sub.shape)
        s["seed"], s["yaw_deg"], s["iou"] = int(seeds[i]), float(yaws[j]), float(sub[i, j])
    before = float(np.mean([s["iou"] for s in chosen]))
    t0 = time.time()
    F.refine_sites(chosen, labels_s, ov, os.path.join(work, "cand"), ages, 30, W, H, workers, log=lambda *x: None)
    after = float(np.mean([s["iou"] for s in chosen]))
    layout = os.path.join(work, f"layout_best{k}.txt")
    TR.write_layout(layout, chosen)
    scene, _ = F.evaluate_layout(target, ov, layout, work, base=f"scene_best{k}")
    results[name] = dict(per_plant_before=before, per_plant_after=after, scene=scene, refine_s=time.time() - t0)
    say(f"{name}: per-plant IoU {before:.4f} -> {after:.4f} after refinement; scene IoU {scene['iou']:.4f}")

json.dump(dict(frame=path, overrides=extra, seeds=a.seeds, curve=curve, refined=results, scores=scores), open(os.path.join(work, "seed_budget.json"), "w"))
say("done")
