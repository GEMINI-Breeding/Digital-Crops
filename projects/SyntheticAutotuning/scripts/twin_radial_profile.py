"""Radial profile of projected leaf area about each plant's stem: can it tell an annulus from a disc?

Every aggregate we have fitted -- cover, footprint area, IoU, even the "spread" descriptor (share of area beyond half
the maximum radius) -- takes the same value for a ring and for a disc of equal area, so none of them can see the
failure mode where every blade sits at one radius and the middle of the plant is empty. This measures the radial
DENSITY: leaf area per unit of annulus area against distance from the stem, normalized so a uniform disc is flat at 1
and a ring shows a displaced mode.

The centre is each plant's stem base, taken from the fitted layout rather than from the mask's centroid: a plant whose
leaves are pushed to one side has a centroid that is not its stem, which would smear exactly the structure being
looked for.

Two cautions carried over from the tomato fit, which hit this same shape: the real profile can have a hole put in it by
occlusion or by segmentation merging central leaves, so the measured centre is not automatically truth; and any
aggregate can be satisfied by the wrong composition, so a matching profile is necessary rather than sufficient.

usage: twin_radial_profile.py [--frame FRAME] [--suffix _final] [--overrides ov.json] [--bins 10]
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
ap.add_argument("--overrides", default=os.path.join(TR.PROJECT, "twin_work", "shapefit_ov.json"))
ap.add_argument("--bins", type=int, default=10)
ap.add_argument("--out", default=None)
a = ap.parse_args()

work = os.path.join(TR.PROJECT, "twin_work", a.frame + a.suffix)
fit = json.load(open(os.path.join(work, "fit.json")))
ov = json.load(open(a.overrides))
ov["canopy.layout_file"] = os.path.join(work, "layout.txt")
target = F.Target(fit["target"], work)
target.plants(1500)
veg_s, valid_s, labels_s = target.downsampled(F.px_scale(ov))


def profile(mask, cx, cy, bins):
    """Leaf area per unit annulus area against r/r95, normalized so a uniform disc reads 1 everywhere."""
    ys, xs = np.nonzero(mask)
    if len(ys) < 50:
        return None
    r = np.hypot(xs - cx, ys - cy)
    r95 = np.percentile(r, 95)
    if r95 <= 0:
        return None
    u = r / r95
    edges = np.linspace(0, 1.0, bins + 1)
    counts, _ = np.histogram(u[u <= 1.0], bins=edges)
    ring_area = np.pi * (edges[1:] ** 2 - edges[:-1] ** 2)      # area of each annulus in the same normalized units
    density = counts / ring_area
    return density / max(density.mean(), 1e-9)


maps = TR.run(ov, seed=1, folder=os.path.join(work, "radial"), base="radial")
site = maps.full("site", 0)
# Blade pixels separately from all of the plant's pixels. A petiole is vegetation, and a plant whose blades all sit
# at one radius still fills its own middle with the stalks that carry them -- so the whole-plant profile can look
# like a disc while the leaf area is a ring. The photograph cannot be split this way, so the blade profile is read
# against the twin's own whole-plant profile, not against the real one.
leaf = maps.full("class", 0) == 1

real_profiles, syn_profiles, blade_profiles = [], [], []
for k, s in enumerate(fit["sites"]):
    cx, cy = s["px"], s["py"]                                   # stem base as fitted, in the raster's pixels
    pr = profile(labels_s == s["label"], cx, cy, a.bins)
    ps = profile(site == k + 1, cx, cy, a.bins)
    pb = profile((site == k + 1) & leaf, cx, cy, a.bins)
    if pr is not None:
        real_profiles.append(pr)
    if ps is not None:
        syn_profiles.append(ps)
    if pb is not None:
        blade_profiles.append(pb)

real = np.median(np.array(real_profiles), axis=0)
syn = np.median(np.array(syn_profiles), axis=0)
blade = np.median(np.array(blade_profiles), axis=0)
edges = np.linspace(0, 1, a.bins + 1)
print(f"{len(real_profiles)} real plants, {len(syn_profiles)} synthetic; radial density, 1.0 = uniform disc\n")
print(f"{'r/r95':>12} {'real':>7} {'twin':>7} {'blades':>7}   {'':<28}")
for i in range(a.bins):
    bar_r = "#" * int(round(real[i] * 12))
    bar_b = "#" * int(round(blade[i] * 12))
    print(f"{edges[i]:5.2f}-{edges[i+1]:4.2f} {real[i]:7.2f} {syn[i]:7.2f} {blade[i]:7.2f}   real {bar_r:<14} twin blades {bar_b}")
peak_r = float(edges[:-1][np.argmax(real)] + 0.5 / a.bins)
peak_s = float(edges[:-1][np.argmax(syn)] + 0.5 / a.bins)
inner_r = float(real[: a.bins // 3].mean())
inner_s = float(syn[: a.bins // 3].mean())
print(f"\npeak density at r/r95: real {peak_r:.2f}, twin {peak_s:.2f}")
inner_b = float(blade[: a.bins // 3].mean())
print(f"inner third mean density: real {inner_r:.2f}, twin {inner_s:.2f}, twin blades only {inner_b:.2f}"
      f"   -> the twin's centre carries {100 * inner_s / max(inner_r, 1e-9):.0f}% of the real density,"
      f" {100 * inner_b / max(inner_r, 1e-9):.0f}% counting blades alone")
path = a.out or os.path.join(TR.PROJECT, "twin_work", f"radial_profile_{a.frame}.json")
json.dump(dict(edges=edges.tolist(), real=real.tolist(), twin=syn.tolist(), peak_real=peak_r, peak_twin=peak_s,
               inner_real=inner_r, inner_twin=inner_s, blades=blade.tolist(), inner_blades=inner_b), open(path, "w"), indent=1)
print("wrote", path)
