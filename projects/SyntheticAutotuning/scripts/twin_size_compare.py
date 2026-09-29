"""Crops of the hand-labelled plants from one or more twin variants, beside the real photo.

The crop rectangles come from twin_work/labels/index.json, so they are the same pixels the labels in the artifact were
clicked on and a variant's crop can be labelled against them directly. Each variant is developed with its own gain fitted
to the real frame's foliage lightness, as the labelling crops were.

usage: twin_size_compare.py --variants soilfix:current,size_petiole:petiole,size_both:both [--frame FRAME] [--sheet out.jpg]
  --variants  comma-separated <workdir suffix>:<tag> pairs; crops land in twin_work/labels/crops/<id>_<tag>.jpg
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
import twin.real as R  # noqa: E402

WB = (1.563, 1.0, 1.596)
ap = argparse.ArgumentParser()
ap.add_argument("--variants", default="soilfix:current")
ap.add_argument("--frame", default="2023-06-20_Plot286-MAGIC083")
ap.add_argument("--sheet", default=os.path.join(TR.PROJECT, "twin_work", "labels", "size_compare.jpg"))
ap.add_argument("--pane", type=int, default=460, help="pane size in the sheet, px")
a = ap.parse_args()

ccm = A.CP.read_ccm(os.path.join(TR.PROJECT, "calib", "ccm_camA_20230728.xml"))
crops_dir = os.path.join(TR.PROJECT, "twin_work", "labels", "crops")
index = [c for c in json.load(open(os.path.join(TR.PROJECT, "twin_work", "labels", "index.json"))) if c["frame"] == a.frame]
variants = [v.split(":") for v in a.variants.split(",")]

fit = json.load(open(os.path.join(TR.PROJECT, "twin_work", a.frame + "_fixD", "fit.json")))
target = F.Target(fit["target"], os.path.join(TR.PROJECT, "twin_work", a.frame + "_fixD"))
real_L50 = A.lab_stats(target.rgb, target.veg)["L50"]

panes = {"real": target.rgb}
for suffix, tag in variants:
    rd = os.path.join(TR.PROJECT, "twin_work", f"{a.frame}_{suffix}", "render_soil")
    exr = glob.glob(os.path.join(rd, "*_raw.exr"))
    if not exr:
        raise SystemExit(f"no render in {rd}")
    raw = A.read_exr(exr[0])
    site = A.label_map(glob.glob(os.path.join(rd, "*_site.txt"))[0])
    panes[tag] = A.develop(raw, A.fit_gain(raw, real_L50, site > 0, wb=WB, ccm=ccm), wb=WB, ccm=ccm)

rows, cover = [], {}
for c in index:
    x0, y0, n = c["x0"], c["y0"], c["crop_px"]
    row = []
    for tag, img in panes.items():
        sub = img[y0:y0 + n, x0:x0 + n]
        if tag != "real":
            cv2.imwrite(os.path.join(crops_dir, f'{c["id"]}_{tag}.jpg'), cv2.cvtColor(sub, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 92])
        cover.setdefault(tag, []).append(float(R.vegetation_mask(sub).mean()))
        pane = cv2.resize(cv2.cvtColor(sub, cv2.COLOR_RGB2BGR), (a.pane, a.pane), interpolation=cv2.INTER_AREA)
        cv2.putText(pane, tag, (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(pane, tag, (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1, cv2.LINE_AA)
        row.append(pane)
    rows.append(np.hstack([np.hstack([p, np.full((a.pane, 6, 3), 255, np.uint8)]) for p in row]))
sheet = np.vstack([np.vstack([r, np.full((6, rows[0].shape[1], 3), 255, np.uint8)]) for r in rows])
cv2.imwrite(a.sheet, sheet, [cv2.IMWRITE_JPEG_QUALITY, 92])

print(f"{len(index)} crops x {len(panes)} panes -> {a.sheet}")
print("vegetation cover in the labelled crops:")
for tag, v in cover.items():
    print(f"  {tag:10s} " + "  ".join(f"{x * 100:5.1f}%" for x in v) + f"   mean {np.mean(v) * 100:5.1f}%")
