"""Evaluate a chlorophyll x specular render grid against the real frame.

For each grid render: develop with the calibrated chain (gain to the real foliage L*), measure
foliage L*/a*/b* medians, the p95 of foliage L* and the fraction of foliage pixels that are
highlights (L* > 70 and chroma < 25), against the same statistics on the real frame; write a
contact sheet of one real plant crop beside the same plant in every grid cell.
usage: twin_leafgrid_eval.py <workdir> [--plant k]
"""
import argparse
import glob
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import twin.appearance as A  # noqa: E402
import twin.fit as F  # noqa: E402
import twin.raster as TR  # noqa: E402
import twin.real as R  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("work"); ap.add_argument("--plant", type=int, default=0)
a = ap.parse_args()
work = os.path.abspath(a.work)
fit = json.load(open(os.path.join(work, "fit.json")))
t = F.Target(fit["target"], work)
t.plants()
WB = (1.563, 1.0, 1.596)
ccm = A.CP.read_ccm(os.path.join(TR.PROJECT, "calib", "ccm_camA_20230728.xml"))


def foliage_stats(rgb, mask):
    lab = R.lab(rgb)
    L, aa, b = lab[..., 0][mask], lab[..., 1][mask], lab[..., 2][mask]
    chroma = np.hypot(aa, b)
    return dict(L50=float(np.median(L)), a50=float(np.median(aa)), b50=float(np.median(b)), L95=float(np.percentile(L, 95)),
                highlight=float(((L > 70) & (chroma < 25)).mean()), sat_med=float(np.median(chroma / np.maximum(L, 1))))


rs = foliage_stats(t.rgb, t.veg)
print(f"real     : L50 {rs['L50']:.1f} a50 {rs['a50']:.1f} b50 {rs['b50']:.1f} L95 {rs['L95']:.1f} highlight {rs['highlight']*100:.2f}%")
# crop of one real plant
plants = sorted(t.plants(), key=lambda p: -p["area_px"])
p = plants[a.plant]
x, y, w, h = p["bbox"]; c = max(w, h) + 60; cx, cy = x + w // 2, y + h // 2
x0, y0 = max(0, cx - c // 2), max(0, cy - c // 2)
tile = 260
real_crop = cv2.resize(t.rgb[y0:y0 + c, x0:x0 + c], (tile, tile), interpolation=cv2.INTER_AREA)
cv2.putText(real_crop, "real", (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
cells = [real_crop]
rows = []
for d in sorted(glob.glob(os.path.join(work, "grid_cab*_spec*"))):
    exr = glob.glob(os.path.join(d, "*_raw.exr"))
    if not exr:
        continue
    raw = A.read_exr(exr[0])
    site = A.label_map(glob.glob(os.path.join(d, "*_site.txt"))[0])
    veg = site > 0
    # half-resolution render: real masks downsampled to it
    g = A.fit_gain(raw, rs["L50"], veg, wb=WB, ccm=ccm)
    dev = A.develop(raw, g, wb=WB, ccm=ccm)
    s = foliage_stats(dev, veg)
    name = os.path.basename(d).replace("grid_", "")
    rows.append(dict(name=name, **s))
    print(f"{name:14s}: L50 {s['L50']:.1f} a50 {s['a50']:.1f} b50 {s['b50']:.1f} L95 {s['L95']:.1f} highlight {s['highlight']*100:.2f}%  gain {g:.0f}")
    sc = dev.shape[1] / R.WIDTH
    crop = dev[int(y0 * sc):int((y0 + c) * sc), int(x0 * sc):int((x0 + c) * sc)]
    crop = cv2.resize(crop, (tile, tile), interpolation=cv2.INTER_AREA)
    cv2.putText(crop, name, (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
    cells.append(crop)
sheet = np.concatenate(cells, axis=1)
cv2.imwrite(os.path.join(work, "leafgrid.jpg"), cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 88])
json.dump(dict(real=rs, grid=rows), open(os.path.join(work, "leafgrid.json"), "w"), indent=1)
print("sheet", os.path.join(work, "leafgrid.jpg"))
