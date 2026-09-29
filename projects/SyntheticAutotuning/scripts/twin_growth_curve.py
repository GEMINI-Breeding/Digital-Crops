"""Emergence and phyllochron fitted jointly against one genotype's growth curve.

Fitting each frame on its own cannot separate when a stand emerged from how fast it accumulates leaf: a plant matches the
same outline younger if it makes leaves faster. Per-frame pinned-age fits showed that directly -- the cover-matching
phyllochron came out 1.5 at 12 days and 2.0 at 25 days on the same plot, which is not a parameter value but a trajectory
shape. This walks the model's cover-versus-age curve for each phyllochron on each frame's own fitted layout (positions,
yaws and seeds held), then finds the single (emergence, phyllochron) pair whose curve passes through all three dates'
real cover at once.

usage: twin_growth_curve.py [--plot Plot286-MAGIC083] [--suffix _yawfix] [--workers 8]
"""
import argparse
import datetime
import itertools
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np  # noqa: E402

import twin.fit as F  # noqa: E402
import twin.raster as TR  # noqa: E402

AGES = (6, 9, 12, 15, 18, 21, 25, 29, 33)
PHYLLOCHRON = (1.0, 1.5, 2.0, 2.7)

ap = argparse.ArgumentParser()
ap.add_argument("--plot", default="Plot286-MAGIC083")
ap.add_argument("--suffix", default="_yawfix")
ap.add_argument("--overrides", default=os.path.join(TR.PROJECT, "twin_work", "size_refit_ov.json"))
ap.add_argument("--workers", type=int, default=8)
ap.add_argument("--out", default=os.path.join(TR.PROJECT, "twin_work", "growth_curve.json"))
a = ap.parse_args()

frames = sorted(os.path.basename(d)[: -len(a.suffix)] for d in
                __import__("glob").glob(os.path.join(TR.PROJECT, "twin_work", f"*{a.plot}{a.suffix}")))
base_ov = json.load(open(a.overrides))


def one(job):
    fr, phy, age = job
    work = os.path.join(TR.PROJECT, "twin_work", fr + a.suffix)
    fit = json.load(open(os.path.join(work, "fit.json")))
    sites = [dict(s, age=float(age)) for s in fit["sites"]]
    tag = f"gc_{phy}_{age}"
    layout = os.path.join(work, tag + "_layout.txt")
    TR.write_layout(layout, sites)
    ov = dict(base_ov)
    ov["canopy.phyllochron"] = phy
    target = F.Target(fit["target"], work)
    sc, _ = F.evaluate_layout(target, ov, layout, os.path.join(work, "gc"), base=tag)
    os.remove(layout)
    return fr, phy, age, sc["cover_syn"], sc["cover_real"], sc["iou"]


jobs = [(fr, phy, age) for fr in frames for phy in PHYLLOCHRON for age in AGES]
print(f"{len(frames)} frames x {len(PHYLLOCHRON)} phyllochron x {len(AGES)} ages = {len(jobs)} scene rasters")
with ProcessPoolExecutor(max_workers=a.workers) as ex:
    res = list(ex.map(one, jobs))

curve, real = {}, {}
for fr, phy, age, syn, rl, iou in res:
    curve.setdefault((fr, phy), {})[age] = syn
    real[fr] = rl
for fr in frames:
    print(f"\n{fr}  real cover {real[fr]:.3f}")
    print(f"{'phy':>5}" + "".join(f"{a_:>8}" for a_ in AGES))
    for phy in PHYLLOCHRON:
        print(f"{phy:5.1f}" + "".join(f"{curve[(fr, phy)][a_]:8.3f}" for a_ in AGES))

# One emergence date and one phyllochron for all three dates
best = None
for phy in PHYLLOCHRON:
    for emergence_offset in np.arange(-14, 1, 0.25):  # days relative to the earliest frame
        errs = []
        for fr in frames:
            date = datetime.date.fromisoformat(fr[:10])
            age = (date - datetime.date.fromisoformat(frames[0][:10])).days - emergence_offset
            if age < AGES[0] or age > AGES[-1]:
                errs = None
                break
            syn = np.interp(age, AGES, [curve[(fr, phy)][a_] for a_ in AGES])
            errs.append(syn / real[fr] - 1.0)
        if errs is None:
            continue
        rms = float(np.sqrt(np.mean(np.square(errs))))
        emergence = datetime.date.fromisoformat(frames[0][:10]) + datetime.timedelta(days=float(emergence_offset))
        if best is None or rms < best[0]:
            best = (rms, phy, emergence, errs)
rms, phy, emergence, errs = best
print(f"\njoint fit: emergence {emergence}, phyllochron {phy} d/node -> rms cover error {100 * rms:.1f}%")
for fr, e in zip(frames, errs):
    age = (datetime.date.fromisoformat(fr[:10]) - emergence).days
    print(f"   {fr}  age {age:2d} d  cover error {100 * e:+.1f}%")
json.dump(dict(curve={f"{k[0]}|{k[1]}": v for k, v in curve.items()}, real=real,
               best=dict(rms=rms, phyllochron=phy, emergence=str(emergence))), open(a.out, "w"), indent=1)
print("wrote", a.out)
