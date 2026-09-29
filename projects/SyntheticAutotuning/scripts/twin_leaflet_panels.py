"""SAM's accepted leaflet masks drawn on real plant crops, to judge its recall on photos by eye.
usage: twin_leaflet_panels.py [frame] [n_plants]
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cv2, numpy as np
import twin.fit as F, twin.leaflets as L, twin.raster as TR

fr = sys.argv[1] if len(sys.argv) > 1 else "2023-06-27_Plot298-MAGIC226"
n = int(sys.argv[2]) if len(sys.argv) > 2 else 4
tw = os.path.join(TR.PROJECT, "twin_work", fr + "_leaf")
fit = json.load(open(os.path.join(tw, "fit.json")))
t = F.Target(fit["target"], tw); t.plants(min_area_px=1500)
os.environ.pop("YOLO_OFFLINE", None); os.environ.pop("ULTRALYTICS_OFFLINE", None)
from ultralytics import SAM
sam = SAM(os.path.join(TR.PROJECT, "weights", "mobile_sam.pt"))
sites = sorted(fit["sites"], key=lambda s: -s["area_s"])[: 2 * n : 2]
tiles = []
for s in sites:
    pm = t.plant_labels == s["label"]
    ys, xs = np.nonzero(pm)
    x0, x1, y0, y1 = max(0, xs.min() - 24), xs.max() + 25, max(0, ys.min() - 24), ys.max() + 25
    crop = t.rgb[y0:y1, x0:x1].copy()
    # re-run the filters to keep the masks for drawing
    res = sam(np.ascontiguousarray(crop[..., ::-1]), verbose=False, device=0)
    h, w = crop.shape[:2]
    pmc = pm[y0:y1, x0:x1]
    masks = []
    for m in res[0].masks.data.cpu().numpy():
        mk = m > 0.5
        if mk.shape != pmc.shape:
            mk = cv2.resize(mk.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST) > 0
        a = int(mk.sum())
        if a == 0 or pmc[mk].mean() < L.MIN_VEG_FRACTION or a > L.MAX_PLANT_FRACTION * pmc.sum():
            continue
        yy, xx = np.nonzero(mk)
        if yy.min() == 0 or xx.min() == 0 or yy.max() == h - 1 or xx.max() == w - 1:
            continue
        masks.append(mk)
    masks.sort(key=lambda m: -int(m.sum()))
    claimed = np.zeros(pmc.shape, bool)
    out = crop.copy()
    rng = np.random.default_rng(1)
    kept = 0
    for mk in masks:
        if (claimed & mk).sum() > 0.3 * mk.sum() or L.segment_stats(mk) is None:
            continue
        claimed |= mk
        kept += 1
        col = rng.integers(60, 255, 3)
        out[mk] = (0.45 * out[mk] + 0.55 * col).astype(np.uint8)
    edge = cv2.morphologyEx(pmc.astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)) > 0
    out[edge] = (255, 0, 255)
    both = np.concatenate([crop, out], axis=1)
    cv2.putText(both, f"{kept} leaflets kept of {len(masks)} candidate masks", (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    tiles.append(both)
W = max(t_.shape[1] for t_ in tiles)
sheet = np.concatenate([np.pad(t_, ((0, 4), (0, W - t_.shape[1]), (0, 0))) for t_ in tiles], axis=0)
os.makedirs(os.path.join(TR.PROJECT, "twin_work", "leaflets"), exist_ok=True)
cv2.imwrite(os.path.join(TR.PROJECT, "twin_work", "leaflets", f"sam_panels_{fr}.jpg"), cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
print("wrote", sheet.shape)
