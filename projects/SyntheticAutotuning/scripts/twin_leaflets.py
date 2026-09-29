"""Leaf-level comparison of the five fitted frames: real (SAM on the photo) against the twin (exact, from the raster).

Before a SAM measure of a photo is compared with an exact measure of the model, SAM is checked where the truth is known: the
same twin scene is rendered, developed, and put through the identical SAM path, and its per-plant statistics are set against
the raster's exact leaflet segments for the same plants. Only a measure on which SAM agrees with the truth is used for fitting.

Writes twin_work/leaflets/leaflets.json and prints per-frame tables.
usage: twin_leaflets.py [frame ...]
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

#: work directory suffix of the fits to measure (TWIN_SUFFIX, default "_leaf"); results go to leaflets<suffix>.json
SUFFIX = os.environ.get("TWIN_SUFFIX", "_leaf")
FRAMES = sys.argv[1:] or ["2023-06-20_Plot286-MAGIC083", "2023-06-20_Plot201-MAGIC262", "2023-06-27_Plot286-MAGIC083", "2023-06-27_Plot298-MAGIC226", "2023-07-03_Plot286-MAGIC083"]
WB = (1.563, 1.0, 1.596)
ccm = A.CP.read_ccm(os.path.join(TR.PROJECT, "calib", "ccm_camA_20230728.xml"))
OUT = os.path.join(TR.PROJECT, "twin_work", "leaflets")
os.makedirs(OUT, exist_ok=True)

os.environ.pop("YOLO_OFFLINE", None)
os.environ.pop("ULTRALYTICS_OFFLINE", None)
from ultralytics import SAM  # noqa: E402

sam = SAM(os.path.join(TR.PROJECT, "weights", "mobile_sam.pt"))


def half_scale_mask(mask):
    """A full-resolution mask at the rasterizer's 0.5 scale, as twin.fit.Target.downsampled makes the vegetation mask."""
    h, w = mask.shape
    return cv2.resize(mask.astype(np.uint8), (int(round(w * 0.5)), int(round(h * 0.5))), interpolation=cv2.INTER_AREA) > 0.5


def pooled(per_plant, key):
    segs = [s for p in per_plant for s in p["segments"]]
    return L.summarise(segs) | dict(n_plants=len(per_plant), n_per_plant=float(np.mean([len(p["segments"]) for p in per_plant])),
                                   thin=float(np.mean([p["thin"] for p in per_plant])) if key != "render_sam" else None)


results = {}
for fr in FRAMES:
    tw = os.path.join(TR.PROJECT, "twin_work", fr + SUFFIX)
    fit = json.load(open(os.path.join(tw, "fit.json")))
    t = F.Target(fit["target"], tw)
    t.plants(min_area_px=1500)
    scene = TR.Maps(tw, "scene")
    rd = os.path.join(tw, "render_soil")
    raw = A.read_exr(glob.glob(os.path.join(rd, "*_raw.exr"))[0])
    render_site = A.label_map(glob.glob(os.path.join(rd, "*_site.txt"))[0])
    render_img = A.develop(raw, A.fit_gain(raw, A.lab_stats(t.rgb, t.veg)["L50"], render_site > 0, wb=WB, ccm=ccm), wb=WB, ccm=ccm)

    rows = dict(real_sam=[], twin_raster=[], render_sam=[])
    for k, s in enumerate(fit["sites"]):
        site_id = k + 1
        real_mask = t.plant_labels == s["label"]
        real_area = float(real_mask.sum())
        rows["real_sam"].append(dict(label=s["label"], segments=L.sam_leaflets(sam, t.rgb, real_mask), thin=L.thin_fraction(half_scale_mask(real_mask))))
        syn_veg = np.isin(scene.site, [site_id]) & np.isin(scene.arrays["class"], TR.VEG_CLASSES)
        rows["twin_raster"].append(dict(label=s["label"], segments=L.synthetic_leaflets(scene.obj, scene.arrays["class"], scene.site, site_id, scale=2.0),
                                        thin=L.thin_fraction(syn_veg)))
        rmask = render_site == site_id
        rows["render_sam"].append(dict(label=s["label"], segments=L.sam_leaflets(sam, render_img, rmask), thin=0.0))

    summary = {key: pooled(v, key) for key, v in rows.items()}
    results[fr] = dict(summary=summary, per_plant={key: [dict(label=p["label"], thin=p["thin"], **L.summarise(p["segments"])) for p in v] for key, v in rows.items()},
                       segments={key: [p["segments"] for p in v] for key, v in rows.items()})
    print(f"\n{fr}  ({len(fit['sites'])} plants)")
    print(f"  {'':34s} {'leaflets/plant':>14s} {'length px':>10s} {'width px':>9s} {'width/len':>9s} {'sqrt area':>9s} {'thin frac':>9s}")
    for key, label in (("real_sam", "real, SAM"), ("twin_raster", "twin, exact (raster)"), ("render_sam", "twin render, SAM (check)")):
        m = summary[key]
        thin = f"{m['thin']:.3f}" if m["thin"] is not None else "-"
        print(f"  {label:34s} {m['n_per_plant']:14.1f} {m['major']:10.1f} {m['minor']:9.1f} {m['aspect']:9.2f} {m['sqrt_area']:9.1f} {thin:>9s}")
    json.dump(results, open(os.path.join(OUT, "leaflets.json" if SUFFIX == "_leaf" else f"leaflets{SUFFIX}.json"), "w"))

print("\nLEAFLETS COMPLETE")
