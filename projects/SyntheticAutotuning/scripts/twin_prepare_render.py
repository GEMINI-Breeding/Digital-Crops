"""Prepare a fitted work directory for the twin render: the frame's soil albedo map at the fit's
camera height, and the per-frame leaf optics (chlorophyll from the frame's foliage colour on the
Plot298 calibration curve, specular 0.02).
usage: twin_prepare_render.py <workdir> [<workdir> ...]
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import twin.appearance as A  # noqa: E402
import twin.fit as F  # noqa: E402
import twin.raster as TR  # noqa: E402
import twin.soil as S  # noqa: E402

#: chlorophyll -> developed foliage (a*, b*) at specular 0.02, from the Plot298 grid render
CAB_CURVE = [(20, -11.0, 49.0), (30, -16.0, 47.0), (40, -19.0, 41.0), (55, -21.0, 34.0)]
MEDIAN_SOIL_REFLECTANCE = 0.0156  # fitted on the 06-20 Plot286 EXR


def fit_cab(a_real, b_real):
    cabs = np.array([c for c, _, _ in CAB_CURVE]); av = np.array([a for _, a, _ in CAB_CURVE]); bv = np.array([b for _, _, b in CAB_CURVE])
    grid = np.arange(15, 90, 0.5)
    ai = np.interp(grid, cabs, av); bi = np.interp(grid, cabs, bv)
    for arr, src in ((ai, av), (bi, bv)):
        hi = grid > cabs[-1]; slope = (src[-1] - src[-2]) / (cabs[-1] - cabs[-2]); arr[hi] = src[-1] + slope * (grid[hi] - cabs[-1])
    return float(grid[np.argmin(np.abs(ai - a_real) + 0.5 * np.abs(bi - b_real))])


ccm = A.CP.read_ccm(os.path.join(TR.PROJECT, "calib", "ccm_camA_20230728.xml"))
rover = np.load(os.path.join(TR.PROJECT, "calib", "rover_mask_full.npy"))
for work in sys.argv[1:]:
    work = os.path.abspath(work)
    fit = json.load(open(os.path.join(work, "fit.json")))
    t = F.Target(fit["target"], work, rover_mask=rover)
    h = float(fit["overrides"].get("camera.height", 1.55))
    amap, meta = S.albedo_map(t, h, ccm, median_reflectance=MEDIAN_SOIL_REFLECTANCE, inpaint_radius=15)
    S.write_map(os.path.join(work, "soil_albedo.bin"), amap, meta)
    S.preview(amap, os.path.join(work, "soil_albedo_preview.png"))
    t2 = F.Target(fit["target"], work)
    rs = A.lab_stats(t2.rgb, t2.veg)
    cab = fit_cab(rs["a50"], rs["b50"])
    open(os.path.join(work, "leaf_overrides.txt"), "w").write(f"leaf.nitrogen_model 0 leaf.chlorophyll {cab:.1f} leaf.specular_scale 0.02\n")
    print(f"{os.path.basename(work)}: camera height {h:.3f}, soil map written, foliage a*/b* {rs['a50']:.0f}/{rs['b50']:.0f} -> chlorophyll {cab:.0f}")
