"""Why per-plant footprints do not overlap: search, model capacity, or a ceiling nothing can beat.

Per-plant silhouette IoU sits at a median of 0.42 over 81 fitted plants. Three explanations have opposite remedies, so
this measures which one is operating before any effort is spent:

  seeds     Best-of-N IoU against the number of plant realizations tried, N = 16 .. 1024 on the same target. Still
            climbing at 1024 means the fit is search-limited and more compute pays; flat by 64 means the model's
            distribution of shapes does not contain this plant and no amount of searching will find it.
  ceiling   Each real plant matched against OTHER REAL PLANTS of similar footprint, best over rotation and translation.
            That is the overlap achievable by a correct cowpea that happens not to be this individual -- the number a
            model cannot exceed without guessing identity from a silhouette. If the fit already sits near it, footprint
            IoU is the wrong thing to keep pushing.
  masks     Whether the real per-plant masks are sound. Two plants merged into one label, or one split in two, caps IoU
            independently of the model, and we have never checked.

usage: twin_footprint_diagnostics.py [--frame FRAME] [--suffix _final] [--seeds 1024] [--plants 4] [--part all]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np  # noqa: E402

import twin.fit as F  # noqa: E402
import twin.raster as TR  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--frame", default="2023-06-27_Plot298-MAGIC226")
ap.add_argument("--suffix", default="_final")
ap.add_argument("--seeds", type=int, default=1024)
ap.add_argument("--plants", type=int, default=4, help="how many target plants to run the seed curve on")
ap.add_argument("--yaws", type=int, default=12)
ap.add_argument("--workers", type=int, default=int(os.environ.get("TWIN_WORKERS", "16")))
ap.add_argument("--part", default="all", choices=["all", "seeds", "ceiling", "masks"])
ap.add_argument("--overrides", default=None)
ap.add_argument("--out", default=None)
a = ap.parse_args()

work = os.path.join(TR.PROJECT, "twin_work", a.frame + a.suffix)
fit = json.load(open(os.path.join(work, "fit.json")))
ov = json.load(open(a.overrides)) if a.overrides else dict(fit["overrides"])
target = F.Target(fit["target"], work)
sc = F.px_scale(ov)
# plants() is what splits merged rows into individual plants, and downsampled() returns whatever labelling the target
# currently holds -- so calling downsampled() first hands back the unsplit one, whose labels do not correspond to the
# ones in fit.json. fit_sparse calls plants() first for this reason; the order is load-bearing, not incidental.
target.plants(1500)
veg_s, valid_s, labels_s = target.downsampled(sc)
sites = fit["sites"]
out = {"frame": a.frame, "suffix": a.suffix, "overrides": ov}

# ---------------------------------------------------------------- masks ---
if a.part in ("all", "masks"):
    stats = []
    mismatched = [s for s in sites if abs((labels_s == s["label"]).sum() - s.get("area_s", 0)) > 0.05 * max(s.get("area_s", 1), 1)]
    if mismatched:
        raise RuntimeError(f"{len(mismatched)} of {len(sites)} site labels do not match the target's labelling "
                           f"(first: label {mismatched[0]['label']}, fit area {mismatched[0].get('area_s', 0):.0f}, "
                           f"mask area {(labels_s == mismatched[0]['label']).sum()}); the labelling is not the one the fit used.")
    for s in sites:
        m = labels_s == s["label"]
        if m.sum() < 50:
            continue
        ys, xs = np.nonzero(m)
        h, w = ys.max() - ys.min() + 1, xs.max() - xs.min() + 1
        hull = float(m.sum()) / max(h * w, 1)
        stats.append(dict(label=int(s["label"]), px=int(m.sum()), elongation=float(max(h, w) / max(min(h, w), 1)),
                          fill=hull, x=float(xs.mean()), y=float(ys.mean())))
    px = np.array([s["px"] for s in stats])
    print(f"masks: {len(stats)} plants, area px median {np.median(px):.0f} "
          f"(p10 {np.percentile(px, 10):.0f}, p90 {np.percentile(px, 90):.0f}, max/median {px.max() / np.median(px):.1f}x)")
    print(f"       elongation median {np.median([s['elongation'] for s in stats]):.2f}, "
          f"bounding-box fill median {np.median([s['fill'] for s in stats]):.2f}")
    suspect = [s for s in stats if s["px"] > 2.5 * np.median(px) or s["elongation"] > 3.0]
    print(f"       {len(suspect)} suspect labels (over 2.5x median area, or elongation above 3): "
          + (", ".join(str(s["label"]) for s in suspect) if suspect else "none"))
    out["masks"] = dict(stats=stats, suspect=[s["label"] for s in suspect])

# ---------------------------------------------------------------- seeds ---
if a.part in ("all", "seeds"):
    order = np.argsort([-s.get("area_s", 0) for s in sites])[: a.plants]
    yaws = np.arange(0, 360, 360 / a.yaws)
    rng = np.random.RandomState(1)
    seeds = rng.randint(1, 2**31 - 1, size=a.seeds)
    curves = {}
    for k in order:
        s = sites[k]
        real_mask = labels_s == s["label"]
        region = F.region_of(real_mask)
        H, W = veg_s.shape
        jobs = [(s["age"], int(seed), s["x"], s["y"], float(y), os.path.join(work, "diag_cand"), f"d{k}_{seed}_{int(y)}")
                for seed in seeds for y in yaws]
        res = F.candidates(ov, jobs, a.workers)
        best_by_seed = []
        for i in range(0, len(jobs), len(yaws)):
            vals = [F.score_candidate(F.place(v, x0, y0, W, H), real_mask, region) for (v, x0, y0) in res[i : i + len(yaws)]]
            best_by_seed.append(max(vals))
        best_by_seed = np.array(best_by_seed)
        running = np.maximum.accumulate(best_by_seed)
        curves[int(s["label"])] = dict(best_by_seed=best_by_seed.tolist(),
                                       at={n: float(running[min(n, len(running)) - 1]) for n in (1, 4, 16, 64, 256, 1024) if n <= len(running)},
                                       fitted=float(s.get("iou", np.nan)))
        c = curves[int(s["label"])]["at"]
        print(f"seeds: plant {s['label']:2d} (area {s.get('area_s', 0):6.0f} px)  best-of-N IoU  "
              + "  ".join(f"N={n}: {v:.3f}" for n, v in c.items()) + f"   fit had {s.get('iou', float('nan')):.3f}")
    out["seed_curves"] = curves

# -------------------------------------------------------------- ceiling ---
if a.part in ("all", "ceiling"):
    masks = {}
    for s in sites:
        m = labels_s == s["label"]
        if m.sum() >= 50:
            ys, xs = np.nonzero(m)
            masks[int(s["label"])] = (m, int(m.sum()), ys, xs)
    labels = sorted(masks)
    ceiling = {}
    for i in labels:
        mi, ai, ysi, xsi = masks[i]
        best = (0.0, None)
        for j in labels:
            if j == i:
                continue
            mj, aj, ysj, xsj = masks[j]
            if not 0.6 < aj / ai < 1.67:      # only plants of comparable size: a different size is a different plant, not a shape mismatch
                continue
            crop = mj[ysj.min():ysj.max() + 1, xsj.min():xsj.max() + 1]
            for rot in range(4):              # rotation in 90 degree steps plus mirroring: cheap stand-in for free rotation
                r = np.rot90(crop, rot)
                for flip in (False, True):
                    rr = r[:, ::-1] if flip else r
                    hh, ww = rr.shape
                    y0 = int(ysi.mean() - hh / 2); x0 = int(xsi.mean() - ww / 2)
                    canvas = np.zeros_like(mi)
                    ys0, xs0 = max(y0, 0), max(x0, 0)
                    ys1, xs1 = min(y0 + hh, mi.shape[0]), min(x0 + ww, mi.shape[1])
                    if ys1 <= ys0 or xs1 <= xs0:
                        continue
                    canvas[ys0:ys1, xs0:xs1] = rr[ys0 - y0 : ys1 - y0, xs0 - x0 : xs1 - x0]
                    v = float((canvas & mi).sum()) / max((canvas | mi).sum(), 1)
                    if v > best[0]:
                        best = (v, j)
        ceiling[i] = dict(iou=best[0], against=best[1])
    vals = np.array([c["iou"] for c in ceiling.values() if c["against"] is not None])
    fitted = np.array([s.get("iou", np.nan) for s in sites])
    print(f"ceiling: real-against-real IoU median {np.median(vals):.3f} (p90 {np.percentile(vals, 90):.3f}) over {len(vals)} plants")
    print(f"         the fit reaches median {np.nanmedian(fitted):.3f} -- {100 * np.nanmedian(fitted) / np.median(vals):.0f}% of the identity-free ceiling")
    out["ceiling"] = {str(k): v for k, v in ceiling.items()}

path = a.out or os.path.join(TR.PROJECT, "twin_work", f"footprint_diagnostics_{a.frame}.json")
json.dump(out, open(path, "w"), indent=1, default=float)
print("wrote", path)
