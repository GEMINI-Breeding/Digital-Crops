"""Fit the parameters that set how a plant spreads, for the stand rather than for one plant.

The footprint diagnostics said per-plant silhouette IoU saturates near 0.50 however many realizations are drawn, while
real plants matched against each other reach 0.63 -- the gap is in what the model can produce, not in the search. What
controls a footprint is branch geometry, and a one-at-a-time sensitivity found two parameters that move it strongly
(petiole flexibility, branch insertion angle) and one that changes silhouette form without changing cover
(phyllotactic angle). None had ever been fitted.

These belong to the stand, not to an individual, so they are fitted once against the DISTRIBUTION of plant shape over
all plants in the frame -- and not against per-plant IoU, which rewards foliage wherever it lands and drove three
earlier sweeps to canopies 40 % too dense. Each plant, real and synthetic, is described by four numbers that are
invariant to where the plant sits and which way it faces:

    area        footprint in pixels, the size the fit already matches through age
    elongation  sqrt of the ratio of the mask's principal second moments: how oblong the outline is
    solidity    area over convex hull area: how much the outline is eaten into by gaps between branches
    spread      share of the footprint lying beyond half the maximum radius: leaf area pushed out from the centre

The objective is the median of each descriptor over the frame's plants, real against synthetic, in units of the real
spread between plants, plus the error in whole-scene cover. The layout -- positions, yaws, ages, seeds -- is held at the
values already fitted, so a candidate is one scene raster.

usage: twin_shape_fit.py [--frame FRAME] [--suffix _final] [--workers 8] [--grid ...]
"""
import argparse
import itertools
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np  # noqa: E402

import twin.fit as F  # noqa: E402
import twin.raster as TR  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--frame", default="2023-06-27_Plot298-MAGIC226")
ap.add_argument("--suffix", default="_final")
ap.add_argument("--overrides", default=os.path.join(TR.PROJECT, "twin_work", "native_angle_ov.json"))
ap.add_argument("--flexibility", default="0,100,300,1000")
ap.add_argument("--insertion", default="30,40,50,60")
ap.add_argument("--phyllotactic", default="none,75,100")
ap.add_argument("--workers", type=int, default=8)
ap.add_argument("--petiole-scale", default=None, help="multipliers on leaf.petiole_length_min/max, e.g. 0.7,0.85,1.0")
ap.add_argument("--pitch-centre", default=None, help="centres for leaf.petiole_pitch_min/max, keeping the current spread")
ap.add_argument("--axes", default=None,
                help="arbitrary grid instead of the three shape knobs: 'key:v1,v2;key2:v1,v2' (use 'none' for leave-unset)")
ap.add_argument("--fixed", default=None, help="'key=value,key2=value2' applied to every candidate")
ap.add_argument("--out", default=None)
a = ap.parse_args()

work = os.path.join(TR.PROJECT, "twin_work", a.frame + a.suffix)
fit = json.load(open(os.path.join(work, "fit.json")))
base_ov = json.load(open(a.overrides))
base_ov["canopy.layout_file"] = os.path.join(work, "layout.txt")
target = F.Target(fit["target"], work)
target.plants(1500)                      # splits merged rows; must run before downsampled(), or the labels are not the fit's
veg_s, valid_s, labels_s = target.downsampled(F.px_scale(base_ov))


RADIAL_BINS = 10


def radial_density(mask, cx, cy, bins=RADIAL_BINS):
    """Leaf area per unit annulus area against r/r95 about the stem, normalized so a uniform disc reads 1.

    The aggregates below cannot tell a ring from a disc of the same area -- both give the same footprint, the same
    cover and the same share of area beyond half the radius -- so where the blades actually sit is measured directly.
    """
    ys, xs = np.nonzero(mask)
    r = np.hypot(xs - cx, ys - cy)
    r95 = np.percentile(r, 95)
    if r95 <= 0:
        return np.full(bins, np.nan)
    u = r / r95
    edges = np.linspace(0, 1.0, bins + 1)
    counts, _ = np.histogram(u[u <= 1.0], bins=edges)
    density = counts / (np.pi * (edges[1:] ** 2 - edges[:-1] ** 2))
    return density / max(density.mean(), 1e-9)


def describe(mask, cx=None, cy=None):
    """area, elongation, solidity, spread -- all invariant to position and orientation."""
    ys, xs = np.nonzero(mask)
    if len(ys) < 30:
        return None
    area = float(len(ys))
    y, x = ys - ys.mean(), xs - xs.mean()
    cov = np.cov(np.stack([x, y]))
    w = np.linalg.eigvalsh(cov)
    elongation = float(np.sqrt(max(w[1], 1e-9) / max(w[0], 1e-9)))
    h, wd = ys.max() - ys.min() + 1, xs.max() - xs.min() + 1
    try:
        import cv2
        cnt, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        hull = max((cv2.contourArea(cv2.convexHull(c)) for c in cnt), default=0.0)
        solidity = float(area / hull) if hull > 0 else float("nan")
    except Exception:
        solidity = float(area / max(h * wd, 1))
    r = np.hypot(x, y)
    spread = float((r > 0.5 * r.max()).mean()) if r.max() > 0 else float("nan")
    out = dict(area=area, elongation=elongation, solidity=solidity, spread=spread)
    if cx is not None:
        out["radial"] = radial_density(mask, cx, cy)
    return out


KEYS = ("area", "elongation", "solidity", "spread")
real = [describe(labels_s == s["label"], s["px"], s["py"]) for s in fit["sites"]]
real = [d for d in real if d]
real_med = {k: float(np.median([d[k] for d in real])) for k in KEYS}
real_iqr = {k: float(np.percentile([d[k] for d in real], 75) - np.percentile([d[k] for d in real], 25)) or 1.0 for k in KEYS}
real_cover = float((veg_s & valid_s).sum() / valid_s.sum())
real_radial = np.nanmedian(np.array([d["radial"] for d in real if "radial" in d]), axis=0)
print(f"real stand ({len(real)} plants): " + "  ".join(f"{k} {real_med[k]:.3f}" for k in KEYS) + f"   cover {real_cover:.3f}")


def evaluate(job):
    idx, params = job
    ov = dict(base_ov)
    ov.update({k: v for k, v in params.items() if v is not None})
    try:
        m = TR.run(ov, seed=1, folder=os.path.join(work, "shapefit"), base=f"s{idx}")
    except Exception as exc:
        return params, None, str(exc)[:120]
    site = m.full("site", 0)
    syn = [describe(site == k + 1, fit["sites"][k]["px"], fit["sites"][k]["py"]) for k in range(len(fit["sites"]))]
    syn = [d for d in syn if d]
    if len(syn) < 0.5 * len(real):
        return params, None, f"only {len(syn)} plants visible"
    syn_med = {k: float(np.median([d[k] for d in syn])) for k in KEYS}
    cover = float((m.full("class", 255) != 255).sum() and (np.isin(m.full("class", 255), [1, 2, 3, 4, 5]) & valid_s).sum() / valid_s.sum())
    syn_radial = np.nanmedian(np.array([d["radial"] for d in syn if "radial" in d]), axis=0)
    radial_err = float(np.nansum(np.abs(syn_radial - real_radial)))
    shape_err = sum(abs(syn_med[k] - real_med[k]) / real_iqr[k] for k in KEYS)
    cover_err = abs(cover - real_cover) / real_cover
    # Weighted so that where the blades sit carries the fit, with cover keeping the total honest: the aggregates that
    # went into shape_err are the ones that proved blind to this failure, so they are kept but not allowed to lead.
    return params, dict(score=2.0 * radial_err + shape_err + 3.0 * cover_err, radial_err=radial_err,
                        radial=syn_radial.tolist(), shape_err=shape_err, cover_err=cover_err,
                        cover=cover, plants=len(syn), **{f"med_{k}": syn_med[k] for k in KEYS}), None


def parse(text, key, cast=float):
    out = []
    for tok in text.split(","):
        out.append(None if tok.strip() == "none" else cast(tok))
    return [{key: v} for v in out]


fixed = {}
if a.fixed:
    for tok in a.fixed.split(","):
        k, v = tok.split("=")
        fixed[k.strip()] = float(v)
if a.petiole_scale or a.pitch_centre:
    axes = []
    if a.petiole_scale:
        base_lo, base_hi = base_ov["leaf.petiole_length_min"], base_ov["leaf.petiole_length_max"]
        axes.append([{"leaf.petiole_length_min": round(base_lo * float(m), 5),
                      "leaf.petiole_length_max": round(base_hi * float(m), 5)} for m in a.petiole_scale.split(",")])
    if a.pitch_centre:
        spread = (base_ov["leaf.petiole_pitch_max"] - base_ov["leaf.petiole_pitch_min"]) / 2.0
        axes.append([{"leaf.petiole_pitch_min": round(float(c) - spread, 3),
                      "leaf.petiole_pitch_max": round(float(c) + spread, 3)} for c in a.pitch_centre.split(",")])
elif a.axes:
    axes = []
    for part in a.axes.split(";"):
        key, values = part.split(":")
        axes.append(parse(values, key.strip()))
else:
    axes = [parse(a.flexibility, "leaf.petiole_flexibility"), parse(a.insertion, "canopy.insertion_angle_tip"),
            parse(a.phyllotactic, "canopy.phyllotactic_angle")]
grid = []
for combo in itertools.product(*axes):
    entry = dict(fixed)
    for part in combo:
        entry.update(part)
    grid.append(entry)
print(f"{len(grid)} candidates, {a.workers} workers")

results = []
with ProcessPoolExecutor(max_workers=a.workers) as ex:
    for params, res, err in ex.map(evaluate, list(enumerate(grid))):
        tag = " ".join(f"{k.split('.')[-1]}={v}" for k, v in params.items())
        if res is None:
            print(f"  {tag:64s} FAILED {err}")
            continue
        results.append((res["score"], params, res))
        print(f"  {tag:56s} score {res['score']:6.3f}  radial {res['radial_err']:5.2f}  solidity {res['med_solidity']:.2f}  cover {res['cover']:.3f}")

results.sort(key=lambda r: r[0])
print("\nbest five:")
for score, params, res in results[:5]:
    print(f"  {score:6.3f}  " + " ".join(f"{k.split('.')[-1]}={v}" for k, v in params.items())
          + f"   elongation {res['med_elongation']:.2f} solidity {res['med_solidity']:.2f} spread {res['med_spread']:.2f} cover {res['cover']:.3f}")
print("  real  " + " " * 8 + f"elongation {real_med['elongation']:.2f} solidity {real_med['solidity']:.2f} spread {real_med['spread']:.2f} cover {real_cover:.3f}")
path = a.out or os.path.join(TR.PROJECT, "twin_work", f"shape_fit_{a.frame}.json")
json.dump(dict(real=real_med, real_cover=real_cover, results=[(s, p, r) for s, p, r in results]), open(path, "w"), indent=1, default=float)
print("wrote", path)
