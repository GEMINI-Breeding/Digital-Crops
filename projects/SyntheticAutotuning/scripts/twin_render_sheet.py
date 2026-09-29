"""Real frame beside twin renders, as full-resolution crops of the plant-dense part of each frame, developed with the calibrated chain.
usage: twin_render_sheet.py <out.jpg> <frame> <workdir_suffix>:<label> [<workdir_suffix>:<label> ...] [--size WxH] [--scale s]
Each workdir twin_work/<frame><suffix> needs render_soil/; the target (real frame) is read from the first suffix that has fit.json.
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cv2  # noqa: E402
import numpy as np  # noqa: E402

import twin.appearance as A  # noqa: E402
import twin.fit as F  # noqa: E402
import twin.raster as TR  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("out")
ap.add_argument("frame")
ap.add_argument("variants", nargs="+")
ap.add_argument("--size", default="700x1000")
ap.add_argument("--scale", type=float, default=0.5)
ap.add_argument("--fit-suffix", default=None, help="workdir suffix holding fit.json, when no variant has one")
a = ap.parse_args()
WB = (1.563, 1.0, 1.596)
ccm = A.CP.read_ccm(os.path.join(TR.PROJECT, "calib", "ccm_camA_20230728.xml"))
cw, ch = (int(x) for x in a.size.split("x"))
variants = [v.split(":", 1) for v in a.variants]
work = lambda suffix: os.path.join(TR.PROJECT, "twin_work", a.frame + suffix)
candidates = ([a.fit_suffix] if a.fit_suffix else []) + [s for s, _ in variants]
fit_dirs = [work(s) for s in candidates if os.path.exists(os.path.join(work(s), "fit.json"))]
if not fit_dirs:
    raise SystemExit(f"no fit.json in any of {[work(s) for s in candidates]}; pass --fit-suffix")
fit_dir = fit_dirs[0]
t = F.Target(json.load(open(os.path.join(fit_dir, "fit.json")))["target"], fit_dir)
ys, xs = np.nonzero(t.veg)
H, W = t.rgb.shape[:2]
y0 = int(np.clip(np.median(ys) - ch // 2, 0, H - ch))
x0 = int(np.clip(np.median(xs) - cw // 2, 0, W - cw))


def label(img, text):
    img = img.copy()
    cv2.putText(img, text, (10, 32), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 5)
    cv2.putText(img, text, (10, 32), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    return img


crops = [label(t.rgb[y0:y0 + ch, x0:x0 + cw], "real")]
for suffix, text in variants:
    rd = os.path.join(work(suffix), "render_soil")
    raw = A.read_exr(glob.glob(os.path.join(rd, "*_raw.exr"))[0])
    site = A.label_map(glob.glob(os.path.join(rd, "*_site.txt"))[0])
    img = A.develop(raw, A.fit_gain(raw, A.lab_stats(t.rgb, t.veg)["L50"], site > 0, wb=WB, ccm=ccm), wb=WB, ccm=ccm)
    crops.append(label(img[y0:y0 + ch, x0:x0 + cw], text))
sep = np.full((ch, 8, 3), 255, np.uint8)
parts = []
for c in crops:
    parts += [c, sep]
sheet = np.concatenate(parts[:-1], 1)
if a.scale != 1.0:
    sheet = cv2.resize(sheet, (int(sheet.shape[1] * a.scale), int(sheet.shape[0] * a.scale)), interpolation=cv2.INTER_AREA)
cv2.imwrite(a.out, cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 90])
print(a.out, sheet.shape)
