"""Leaf-shape fit against the leaflet-aware fit, frame by frame: crops for the eye and the numbers that go with them.

For each frame: a full-resolution crop of the plant-dense part of the real frame beside the same crop of the twin under the
previous parameters (<frame>_leaf) and under the shape fit (<frame><suffix>), both developed with the calibrated chain. Numbers:
scene and median per-plant silhouette IoU from the fits, and visible leaflet length and width (exact, raster) and thin-structure
fraction against the real targets.

usage: twin_shape_compare.py [suffix, default _shape]
"""
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cv2  # noqa: E402
import numpy as np  # noqa: E402

import twin.appearance as A  # noqa: E402
import twin.fit as F  # noqa: E402
import twin.raster as TR  # noqa: E402

SUFFIX = sys.argv[1] if len(sys.argv) > 1 else "_shape"
FRAMES = ["2023-06-20_Plot286-MAGIC083", "2023-06-20_Plot201-MAGIC262", "2023-06-27_Plot286-MAGIC083", "2023-06-27_Plot298-MAGIC226", "2023-07-03_Plot286-MAGIC083"]
WB = (1.563, 1.0, 1.596)
ccm = A.CP.read_ccm(os.path.join(TR.PROJECT, "calib", "ccm_camA_20230728.xml"))
WORK = os.path.join(TR.PROJECT, "twin_work")
OUT = os.path.join(WORK, "report", "shape")
os.makedirs(OUT, exist_ok=True)
targets = json.load(open(os.path.join(WORK, "leaflets", "targets.json")))
leaf_old = json.load(open(os.path.join(WORK, "leaflets", "leaflets.json")))
leaf_new = json.load(open(os.path.join(WORK, "leaflets", f"leaflets{SUFFIX}.json")))


def scene_iou(workdir):
    lines = [l for l in open(os.path.join(workdir, "fit.log")) if l.startswith("scene:")]
    return json.loads(lines[-1][len("scene:"):])


def developed(workdir, t):
    rd = os.path.join(workdir, "render_soil")
    raw = A.read_exr(glob.glob(os.path.join(rd, "*_raw.exr"))[0])
    veg = A.label_map(glob.glob(os.path.join(rd, "*_site.txt"))[0]) > 0
    return A.develop(raw, A.fit_gain(raw, A.lab_stats(t.rgb, t.veg)["L50"], veg, wb=WB, ccm=ccm), wb=WB, ccm=ccm)


def label(img, text):
    img = img.copy()
    cv2.putText(img, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 4)
    cv2.putText(img, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
    return img


rows = []
for fr in FRAMES:
    old_dir, new_dir = os.path.join(WORK, fr + "_leaf"), os.path.join(WORK, fr + SUFFIX)
    fit_new = json.load(open(os.path.join(new_dir, "fit.json")))
    fit_old = json.load(open(os.path.join(old_dir, "fit.json")))
    t = F.Target(fit_new["target"], new_dir)
    old_img, new_img = developed(old_dir, t), developed(new_dir, t)
    ys, xs = np.nonzero(t.veg)
    cy, cx = int(np.median(ys)), int(np.median(xs))
    H, W = t.rgb.shape[:2]
    y0 = int(np.clip(cy - 420, 0, H - 840))
    x0 = int(np.clip(cx - 560, 0, W - 1120))
    crops = [label(im[y0:y0 + 840, x0:x0 + 1120], text) for im, text in ((t.rgb, "real"), (old_img, "twin: leaflet-aware fit"), (new_img, "twin: leaf-shape fit"))]
    sep = np.full((840, 8, 3), 255, np.uint8)
    sheet = np.concatenate([crops[0], sep, crops[1], sep, crops[2]], axis=1)
    cv2.imwrite(os.path.join(OUT, f"cmp_{fr}.jpg"), cv2.cvtColor(cv2.resize(sheet, (sheet.shape[1] * 2 // 3, sheet.shape[0] * 2 // 3), interpolation=cv2.INTER_AREA), cv2.COLOR_RGB2BGR),
                [cv2.IMWRITE_JPEG_QUALITY, 82])
    so, sn = leaf_old[fr]["summary"]["twin_raster"], leaf_new[fr]["summary"]["twin_raster"]
    tg = targets[fr]
    row = dict(frame=fr, scene_iou=dict(old=scene_iou(old_dir)["iou"], new=scene_iou(new_dir)["iou"]),
               plant_iou_median=dict(old=float(np.median([s["iou"] for s in fit_old["sites"]])), new=float(np.median([s["iou"] for s in fit_new["sites"]]))),
               leaflet=dict(target=[tg["major"], tg["minor"]], old=[so["major"], so["minor"]], new=[sn["major"], sn["minor"]]),
               thin=dict(target=tg["thin"], old=so["thin"], new=sn["thin"]),
               leaflets_per_plant=dict(real_sam_floor=tg["n_per_plant"], old=so["n_per_plant"], new=sn["n_per_plant"]))
    rows.append(row)
    print(f"{fr}: scene IoU {row['scene_iou']['old']:.3f} -> {row['scene_iou']['new']:.3f}; plant IoU median {row['plant_iou_median']['old']:.3f} -> {row['plant_iou_median']['new']:.3f}; "
          f"leaflet {so['major']:.0f}x{so['minor']:.0f} -> {sn['major']:.0f}x{sn['minor']:.0f} px (target {tg['major']:.0f}x{tg['minor']:.0f}); thin {so['thin']:.3f} -> {sn['thin']:.3f} (target {tg['thin']:.3f}); "
          f"leaflets/plant {so['n_per_plant']:.0f} -> {sn['n_per_plant']:.0f} (real SAM floor {tg['n_per_plant']:.0f})")
json.dump(rows, open(os.path.join(OUT, "compare.json"), "w"), indent=1)
