"""How much stalk the picture shows: the share of foliage that is thin enough to be a petiole.

The radial profile says where a plant's area sits, not how much of its structure is bare stalk, and the two
disagree -- the blade/petiole rate split that best matches the radial profile hides the petioles almost
entirely, where the photograph shows some. This measures that directly and, unlike a class map, it can be
measured the same way on the photograph: a petiole is about two or three pixels across at this scale and a
leaflet about thirty-five, so a morphological opening with a small disc removes the stalks and keeps the
blades. The share of vegetation pixels the opening removes is the "thin fraction".

It is a proxy, not a segmentation: leaf edges and any speckle in the real mask are thin too, so the absolute
number carries a floor. It is used as a comparison between the twin and the photograph developed through the
same pipeline at the same resolution, never as an absolute.

usage: twin_thin_fraction.py [--frames FR,FR] [--radius 3]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cv2  # noqa: E402
import numpy as np  # noqa: E402

import twin.fit as F  # noqa: E402
import twin.raster as TR  # noqa: E402

GRID = [("library, one rate", {}),
        ("blade 0.15 / pet 0.10", {"canopy.leaf_expansion_rate": 0.15}),
        ("blade 0.20 / pet 0.10", {"canopy.leaf_expansion_rate": 0.20}),
        ("blade 0.20 / pet 0.07", {"canopy.leaf_expansion_rate": 0.20, "canopy.elongation_rate": 0.07}),
        ("blade 0.30 / pet 0.07", {"canopy.leaf_expansion_rate": 0.30, "canopy.elongation_rate": 0.07}),
        ("blade 0.30 / pet 0.05", {"canopy.leaf_expansion_rate": 0.30, "canopy.elongation_rate": 0.05}),
        ("blade 0.50 / pet 0.05", {"canopy.leaf_expansion_rate": 0.50, "canopy.elongation_rate": 0.05})]

ap = argparse.ArgumentParser()
ap.add_argument("--frames", default="2023-06-20_Plot286-MAGIC083,2023-06-27_Plot298-MAGIC226")
ap.add_argument("--radius", type=int, default=3)
ap.add_argument("--binary", default=None)
a = ap.parse_args()


def thin_fraction(mask, radius):
    """Share of the mask's pixels that do not survive an opening with a disc of this radius."""
    m = mask.astype(np.uint8)
    total = int(m.sum())
    if total == 0:
        return float("nan")
    disc = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))
    kept = int(cv2.morphologyEx(m, cv2.MORPH_OPEN, disc).sum())
    return 1.0 - kept / total


for frame in a.frames.split(","):
    work = os.path.join(TR.PROJECT, "twin_work", frame + "_final")
    fit = json.load(open(os.path.join(work, "fit.json")))
    base = dict(fit["overrides"])
    base["canopy.layout_file"] = os.path.join(work, "layout.txt")
    target = F.Target(fit["target"], work)
    target.plants(1500)
    veg_real, valid, labels = target.downsampled(F.px_scale(base))
    # Only where a plant was actually labelled, so that weeds and the neighbouring row do not enter.
    real_mask = veg_real & (labels > 0)
    print(f"\n=== {frame} ===  thin fraction, opening radius {a.radius} px")
    print(f"{'setting':24s} {'thin':>7} {'petiole px':>11} {'veg px':>9}")
    print(f"{'REAL':24s} {thin_fraction(real_mask, a.radius):7.3f} {'--':>11} {int(real_mask.sum()):9d}")
    for name, extra in GRID:
        ov = dict(base)
        ov.update(extra)
        ov["raster.split_stems"] = 1
        maps = TR.run(ov, seed=1, folder=os.path.join(TR.PROJECT, "twin_work", "thin"), base="th",
                      binary=a.binary or TR.BINARY)
        cls = maps.full("class", 0)
        veg = np.isin(cls, (1, 2, 3, 4, 5, 7, 8))
        petiole = float(np.isin(cls, (4,)).sum()) / max(int(veg.sum()), 1)
        print(f"{name:24s} {thin_fraction(veg, a.radius):7.3f} {petiole:11.3f} {int(veg.sum()):9d}")
