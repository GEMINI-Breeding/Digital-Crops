"""Where the colour comes from: the same raw EXRs developed with white balance only, then with the colour matrix,
for the naive baseline scene (stock pigments and soil, sun off) and the tuned twin (fitted pigments, soil map).
Gain is fitted to the real foliage L* in every case, so only chroma and hue differ.
usage: twin_colour_decompose.py
"""
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

FRAME = "2023-06-27_Plot298-MAGIC226"
WB = (1.563, 1.0, 1.596)
ccm = A.CP.read_ccm(os.path.join(TR.PROJECT, "calib", "ccm_camA_20230728.xml"))
rover = np.load(os.path.join(TR.PROJECT, "calib", "rover_mask.npy"))
WORK = os.path.join(TR.PROJECT, "twin_work")
OUT = os.path.join(WORK, "report", "wbref")

tw = os.path.join(WORK, FRAME + "_leaf")
t = F.Target(json.load(open(os.path.join(tw, "fit.json")))["target"], tw)
valid = ~rover


def stats(img, veg):
    out = {}
    for name, m in (("foliage", veg & valid), ("soil", (~veg) & valid)):
        s = A.lab_stats(img, m)
        out[name] = dict(L=round(s["L50"]), a=round(s["a50"]), b=round(s["b50"]), C=round(float(np.hypot(s["a50"], s["b50"]))))
    return out


scenes = {"baseline": os.path.join(WORK, "baseline_" + FRAME[:10], "render_fixed_sunoff"), "tuned twin": os.path.join(tw, "render_soil")}
rows = {"real": stats(t.rgb, t.veg)}
panes = []
for label, d in scenes.items():
    raw = A.read_exr(glob.glob(os.path.join(d, "*_raw.exr"))[0])
    veg = A.label_map(glob.glob(os.path.join(d, "*_site.txt"))[0]) > 0
    for step, matrix in (("white balance only", None), ("white balance + colour matrix", ccm)):
        g = A.fit_gain(raw, A.lab_stats(t.rgb, t.veg)["L50"], veg, wb=WB, ccm=matrix)
        img = A.develop(raw, g, wb=WB, ccm=matrix)
        rows[f"{label}, {step}"] = stats(img, veg)
        panes.append((f"{label}: {step}", img))
panes.append(("real", t.rgb))

w = 640
h = int(t.rgb.shape[0] * w / t.rgb.shape[1])
tiles = []
for text, img in panes:
    p = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    cv2.putText(p, text, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3)
    cv2.putText(p, text, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    tiles.append(p)
top = np.concatenate(tiles[0:2] + [tiles[4]], axis=1)
bottom = np.concatenate(tiles[2:4] + [tiles[4]], axis=1)
cv2.imwrite(os.path.join(OUT, "colour_decompose.jpg"), cv2.cvtColor(np.concatenate([top, bottom], axis=0), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 82])
for k, v in rows.items():
    print(f"{k:55s} foliage L {v['foliage']['L']:3d} a {v['foliage']['a']:4d} b {v['foliage']['b']:4d} C {v['foliage']['C']:3d}   soil L {v['soil']['L']:3d} a {v['soil']['a']:4d} b {v['soil']['b']:4d} C {v['soil']['C']:3d}")
json.dump(rows, open(os.path.join(OUT, "colour_decompose.json"), "w"), indent=1)
