"""Stem and petiole colour of a twin render against the real frame, per stem-spectrum candidate.

The render is made with stem.candidates "y:s,..." so that plant k carries candidate k mod K. Petiole pixels are exact on the twin
(the scene raster's class 4, eroded 1 px) and approximate on the photo (vegetation removed by a 9 px opening, eroded 1 px, in pieces
at least 25 px long). Each is compared with the leaves of its own image, so the offsets do not depend on the exposure.
usage: twin_stem_colour.py <workdir> <render_dir> "y:s,y:s,..."
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
import twin.raster as TR  # noqa: E402

WB = (1.563, 1.0, 1.596)
workdir, render_dir, candidates = sys.argv[1], sys.argv[2], sys.argv[3].split(",")
ccm = A.CP.read_ccm(os.path.join(TR.PROJECT, "calib", "ccm_camA_20230728.xml"))


def lab(rgb):
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32) * np.array([100 / 255, 1, 1]) - np.array([0, 128, 128])


def median_lab(rgb, mask):
    return np.median(lab(rgb)[mask], 0)


fit = json.load(open(os.path.join(workdir, "fit.json")))
t = F.Target(fit["target"], workdir)
raw = A.read_exr(glob.glob(os.path.join(render_dir, "*_raw.exr"))[0])
site = A.label_map(glob.glob(os.path.join(render_dir, "*_site.txt"))[0])
img = A.develop(raw, A.fit_gain(raw, A.lab_stats(t.rgb, t.veg)["L50"], site > 0, wb=WB, ccm=ccm), wb=WB, ccm=ccm)
H, W = img.shape[:2]
cls = cv2.resize(TR.Maps(workdir, "scene").arrays["class"], (W, H), interpolation=cv2.INTER_NEAREST)
k3 = np.ones((3, 3), np.uint8)
syn_pet = cv2.erode((cls == 4).astype(np.uint8), k3) > 0
syn_leaf = cv2.erode((cls == 1).astype(np.uint8), np.ones((7, 7), np.uint8)) > 0

veg = t.veg.astype(np.uint8)
opened = cv2.morphologyEx(veg, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
thin = cv2.erode(((veg > 0) & (opened == 0)).astype(np.uint8), k3)
n, lab_cc, st, _ = cv2.connectedComponentsWithStats(thin, connectivity=8)
keep = np.zeros(n, bool)
keep[1:] = np.maximum(st[1:, cv2.CC_STAT_WIDTH], st[1:, cv2.CC_STAT_HEIGHT]) >= 25
real_pet = keep[lab_cc]
real_leaf = cv2.erode(opened, np.ones((7, 7), np.uint8)) > 0
real = median_lab(t.rgb, real_pet) - median_lab(t.rgb, real_leaf)
print(f"real petiole - leaf: dL* {real[0]:+.1f} da* {real[1]:+.1f} db* {real[2]:+.1f}   (petiole px {int(real_pet.sum())})")
out = dict(real=real.tolist(), candidates={})
for k, c in enumerate(candidates):
    plants = np.isin(site, [s + 1 for s in range(64) if s % len(candidates) == k])
    d = median_lab(img, syn_pet & plants) - median_lab(img, syn_leaf & plants)
    err = float(np.linalg.norm(d - real))
    out["candidates"][c] = dict(offset=d.tolist(), delta_E=err, petiole_px=int((syn_pet & plants).sum()))
    print(f"candidate {c:10s} petiole - leaf: dL* {d[0]:+.1f} da* {d[1]:+.1f} db* {d[2]:+.1f}   distance from real {err:.1f}   (petiole px {int((syn_pet & plants).sum())})")
json.dump(out, open(os.path.join(render_dir, "stem_colour.json"), "w"), indent=1)
