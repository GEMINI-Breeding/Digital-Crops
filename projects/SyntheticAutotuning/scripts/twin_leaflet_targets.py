"""Real leaf-level targets for the shape fit, in the raster's terms.

From twin_work/leaflets/leaflets.json (twin_leaflets.py):
  length, width   real SAM medians x (raster / SAM-on-render) for the same frame: SAM's bias measured where the truth is known.
  thin fraction   the real mask misses thin dark petioles, so the real value is the colour-masked one; it is divided by the
                  ratio (colour-masked render / raster) measured on the same frame's twin, which is what the colour mask does
                  to thin structure.
  leaflets/plant  reported only: SAM finds about half the real leaflets (twin_leaflet_panels.py), so it is not a target.

Writes twin_work/leaflets/targets.json.
usage: twin_leaflet_targets.py
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cv2  # noqa: E402
import numpy as np  # noqa: E402

import twin.appearance as A  # noqa: E402
import twin.fit as F  # noqa: E402
import twin.leaflets as L  # noqa: E402
import twin.raster as TR  # noqa: E402
import twin.real as R  # noqa: E402

WB = (1.563, 1.0, 1.596)
ccm = A.CP.read_ccm(os.path.join(TR.PROJECT, "calib", "ccm_camA_20230728.xml"))
data = json.load(open(os.path.join(TR.PROJECT, "twin_work", "leaflets", "leaflets.json")))


def half(m):
    h, w = m.shape
    return cv2.resize(m.astype(np.uint8), (w // 2, h // 2), interpolation=cv2.INTER_AREA) > 0.5


targets = {}
for fr, d in data.items():
    s = d["summary"]
    tw = os.path.join(TR.PROJECT, "twin_work", fr + "_leaf")
    fit = json.load(open(os.path.join(tw, "fit.json")))
    t = F.Target(fit["target"], tw)
    rd = os.path.join(tw, "render_soil")
    raw = A.read_exr(glob.glob(os.path.join(rd, "*_raw.exr"))[0])
    site = A.label_map(glob.glob(os.path.join(rd, "*_site.txt"))[0])
    img = A.develop(raw, A.fit_gain(raw, A.lab_stats(t.rgb, t.veg)["L50"], site > 0, wb=WB, ccm=ccm), wb=WB, ccm=ccm)
    colour = R.vegetation_mask(img)
    full, masked = [], []
    for k in range(len(fit["sites"])):
        sm = site == k + 1
        full.append(L.thin_fraction(half(sm)))
        masked.append(L.thin_fraction(half(sm & colour)))
    thin_ratio = float(np.mean(masked) / max(np.mean(full), 1e-6))
    major_cal = s["twin_raster"]["major"] / s["render_sam"]["major"]
    minor_cal = s["twin_raster"]["minor"] / s["render_sam"]["minor"]
    targets[fr] = dict(major=s["real_sam"]["major"] * major_cal, minor=s["real_sam"]["minor"] * minor_cal, thin=s["real_sam"]["thin"] / thin_ratio,
                       n_per_plant=s["real_sam"]["n_per_plant"], calibration=dict(major=major_cal, minor=minor_cal, thin_mask_ratio=thin_ratio),
                       twin_now=dict(major=s["twin_raster"]["major"], minor=s["twin_raster"]["minor"], thin=s["twin_raster"]["thin"], n_per_plant=s["twin_raster"]["n_per_plant"]))
    g = targets[fr]
    print(f"{fr}: target leaflet {g['major']:.1f} x {g['minor']:.1f} px, thin {g['thin']:.3f}   (twin now {g['twin_now']['major']:.1f} x {g['twin_now']['minor']:.1f}, thin {g['twin_now']['thin']:.3f};"
          f" SAM cal {major_cal:.3f}/{minor_cal:.3f}, mask thin ratio {thin_ratio:.2f})")
json.dump(targets, open(os.path.join(TR.PROJECT, "twin_work", "leaflets", "targets.json"), "w"), indent=1)
