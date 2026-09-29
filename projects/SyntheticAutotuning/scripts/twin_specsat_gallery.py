"""Leaf specular and saturation on the naive baseline scenes (sun off, white-reference auto white balance, fixed specular_scale).

Sheet per frame: real | specular scale 0 | scale 0 + saturation 2.0 | scale 0.02 + saturation 2.0 | scale 0.08 + saturation 2.0 |
tuned twin. Numbers: foliage and soil L*a*b* medians and chroma, and the share of foliage pixels that are near-white highlights
(L* > 80 with chroma < 20).
usage: twin_specsat_gallery.py
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
import twin.real as R  # noqa: E402
from twin_wbref_gallery_orient import orient_jpeg  # noqa: E402

FRAMES = ["2023-06-20_Plot286-MAGIC083", "2023-06-27_Plot298-MAGIC226", "2023-07-03_Plot286-MAGIC083"]
WB = (1.563, 1.0, 1.596)
ccm = A.CP.read_ccm(os.path.join(TR.PROJECT, "calib", "ccm_camA_20230728.xml"))
rover = np.load(os.path.join(TR.PROJECT, "calib", "rover_mask.npy"))
WORK = os.path.join(TR.PROJECT, "twin_work")
OUT = os.path.join(WORK, "report", "wbref")
RENDERS = (("render_fixed_sunoff", "specular 0, saturation 1"), ("render_fixed_spec0_sat2", "specular 0, saturation 2.0"),
           ("render_spec002_sat2", "specular 0.02, saturation 2.0"), ("render_fixed_spec008_sat2", "specular 0.08, saturation 2.0"))


def stats(img, veg):
    lab = R.lab(img)
    out = {}
    for name, m in (("foliage", veg & ~rover), ("soil", (~veg) & ~rover)):
        L, a, b = (float(np.median(lab[..., i][m])) for i in range(3))
        out[name] = [round(L), round(a), round(b), round(float(np.hypot(a, b)))]
    m = veg & ~rover
    C = np.hypot(lab[..., 1], lab[..., 2])
    out["highlight_pct"] = round(100.0 * float(((lab[..., 0] > 80) & (C < 20))[m].mean()), 1)
    return out


def labelled(img, text, w, h):
    pane = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    cv2.putText(pane, text, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3)
    cv2.putText(pane, text, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    return pane


result = []
for fr in FRAMES:
    tw = os.path.join(WORK, fr + "_leaf")
    bw = os.path.join(WORK, "baseline_" + fr[:10])
    t = F.Target(json.load(open(os.path.join(tw, "fit.json")))["target"], tw)
    rd = os.path.join(tw, "render_soil")
    raw = A.read_exr(glob.glob(os.path.join(rd, "*_raw.exr"))[0])
    tveg = A.label_map(glob.glob(os.path.join(rd, "*_site.txt"))[0]) > 0
    twin_img = A.develop(raw, A.fit_gain(raw, A.lab_stats(t.rgb, t.veg)["L50"], tveg, wb=WB, ccm=ccm), wb=WB, ccm=ccm)

    row = dict(frame=fr, real=stats(t.rgb, t.veg), twin=stats(twin_img, tveg))
    panes = []
    for sub, text in RENDERS:
        d = os.path.join(bw, sub)
        braw = A.read_exr(glob.glob(os.path.join(d, "*_raw.exr"))[0])
        jpg = cv2.cvtColor(cv2.imread(glob.glob(os.path.join(d, "*_RGB.jpeg"))[0]), cv2.COLOR_BGR2RGB)
        _, _, img = orient_jpeg(jpg, braw)
        veg = A.label_map(glob.glob(os.path.join(d, "*_site.txt"))[0]) > 0
        row[sub] = stats(img, veg)
        panes.append(labelled(img, text, 760, int(t.rgb.shape[0] * 760 / t.rgb.shape[1])))
    result.append(row)

    w = 760
    h = panes[0].shape[0]
    top = np.concatenate([labelled(t.rgb, "real", w, h), panes[0], panes[1]], axis=1)
    bottom = np.concatenate([panes[2], panes[3], labelled(twin_img, "tuned twin (fitted colour chain)", w, h)], axis=1)
    cv2.imwrite(os.path.join(OUT, f"specsat_{fr}.jpg"), cv2.cvtColor(np.concatenate([top, bottom], axis=0), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 82])
    print(fr)
    for k in ("real",) + tuple(r[0] for r in RENDERS) + ("twin",):
        s = row[k]
        print(f"   {k:22s} foliage L a b C {s['foliage']}  soil {s['soil']}  highlights {s['highlight_pct']}% of foliage")

json.dump(result, open(os.path.join(OUT, "specsat.json"), "w"), indent=1)
