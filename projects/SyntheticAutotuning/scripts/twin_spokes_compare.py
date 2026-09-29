"""Real frame against twin variants, frame by frame, as full-resolution crops for the eye, with scene IoU, median plant IoU and
the share of visible vegetation that is stem or petiole (exact, from each variant's scene raster).
usage: twin_spokes_compare.py suffix:label [suffix:label ...]      writes twin_work/report/diag/spokes_<frame>.jpg and spokes.json
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
FRAMES = ["2023-06-20_Plot286-MAGIC083", "2023-06-20_Plot201-MAGIC262", "2023-06-27_Plot286-MAGIC083", "2023-06-27_Plot298-MAGIC226", "2023-07-03_Plot286-MAGIC083"]
variants = [a.split(":", 1) for a in sys.argv[1:]]
ccm = A.CP.read_ccm(os.path.join(TR.PROJECT, "calib", "ccm_camA_20230728.xml"))
OUT = os.path.join(TR.PROJECT, "twin_work", "report", "diag")


def label(img, text):
    img = img.copy()
    cv2.putText(img, text, (10, 32), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 5)
    cv2.putText(img, text, (10, 32), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    return img


def scene_iou(workdir):
    for line in reversed(open(os.path.join(workdir, "fit.log"), errors="replace").read().splitlines()):
        if line.startswith("scene:"):
            return json.loads(line[len("scene:"):])["iou"]
    raise RuntimeError(f"no scene line in {workdir}/fit.log")


summary = {}
for fr in FRAMES:
    base = os.path.join(TR.PROJECT, "twin_work", fr + variants[0][0])
    t = F.Target(json.load(open(os.path.join(base, "fit.json")))["target"], base)
    ys, xs = np.nonzero(t.veg)
    H, W = t.rgb.shape[:2]
    y0 = int(np.clip(np.median(ys) - 500, 0, H - 1000))
    x0 = int(np.clip(np.median(xs) - 350, 0, W - 700))
    crops = [label(t.rgb[y0:y0 + 1000, x0:x0 + 700], "real")]
    summary[fr] = {}
    for suffix, text in variants:
        wd = os.path.join(TR.PROJECT, "twin_work", fr + suffix)
        rd = os.path.join(wd, "render_soil")
        raw = A.read_exr(glob.glob(os.path.join(rd, "*_raw.exr"))[0])
        site = A.label_map(glob.glob(os.path.join(rd, "*_site.txt"))[0])
        img = A.develop(raw, A.fit_gain(raw, A.lab_stats(t.rgb, t.veg)["L50"], site > 0, wb=WB, ccm=ccm), wb=WB, ccm=ccm)
        cls = TR.Maps(wd, "scene").arrays["class"]
        stem = float((cls == 4).sum() / max(np.isin(cls, TR.VEG_CLASSES).sum(), 1))
        fit = json.load(open(os.path.join(wd, "fit.json")))
        row = dict(scene_iou=scene_iou(wd), plant_iou_median=float(np.median([s["iou"] for s in fit["sites"]])), stem_share=stem)
        summary[fr][suffix] = row
        crops.append(label(img[y0:y0 + 1000, x0:x0 + 700], f"{text}  IoU {row['scene_iou']:.2f}"))
        print(f"{fr:30s} {text:28s} scene IoU {row['scene_iou']:.3f}  median plant IoU {row['plant_iou_median']:.3f}  stem share {stem:.3f}")
    sep = np.full((1000, 8, 3), 255, np.uint8)
    parts = []
    for c in crops:
        parts += [c, sep]
    sheet = np.concatenate(parts[:-1], 1)
    cv2.imwrite(os.path.join(OUT, f"spokes_{fr}.jpg"), cv2.cvtColor(cv2.resize(sheet, (sheet.shape[1] // 2, sheet.shape[0] // 2), interpolation=cv2.INTER_AREA), cv2.COLOR_RGB2BGR),
                [cv2.IMWRITE_JPEG_QUALITY, 88])
json.dump(summary, open(os.path.join(OUT, "spokes.json"), "w"), indent=1)
