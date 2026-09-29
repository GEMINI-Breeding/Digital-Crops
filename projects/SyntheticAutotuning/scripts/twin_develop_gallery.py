"""Develop the rendered twins and build the three-pane gallery figures.

For each fitted work directory (holding fit.json and render_rover/): develop the raw EXR with no
extra white balance, the scene-fit colour matrix, a gain that puts synthetic foliage at the real
foliage L*, and a soil scale fitted on the ground pixels; then write
  <workdir>/three_pane.jpg      real | synthetic | real with synthetic plant masks overlaid
  <workdir>/appearance.json     masked colour statistics, real against synthetic
and a downsized copy in twin_work/report/three_<tag>.jpg.
usage: twin_develop_gallery.py <workdir> [<workdir> ...]
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
import twin.panels as P  # noqa: E402
import twin.raster as TR  # noqa: E402

REPORT = os.path.join(TR.PROJECT, "twin_work", "report")
os.makedirs(REPORT, exist_ok=True)
# Development chain for the calibrated scene (rover shrouding the plot over the LED rig): the
# previous project's illuminant-aware white balance and the colour-board matrix. On the 06-20
# frame this puts foliage at L*/a*/b* 44/-18/+25 against the real 44/-17/+27. (A sun-lit,
# unshaded render needs no extra balance; that is what produced the earlier magenta renders.)
WB = (1.563, 1.0, 1.596)
ccm = A.CP.read_ccm(os.path.join(TR.PROJECT, "calib", "ccm_camA_20230728.xml"))
summary = []
for work in sys.argv[1:]:
    work = os.path.abspath(work)
    tag = os.path.basename(work)
    fit = json.load(open(os.path.join(work, "fit.json")))
    rd = os.path.join(work, "render_soil") if glob.glob(os.path.join(work, "render_soil", "*_raw.exr")) else os.path.join(work, "render_rover")
    exr = glob.glob(os.path.join(rd, "*_raw.exr"))
    if not exr:
        print(tag, "no render yet"); continue
    t = F.Target(fit["target"], work)
    raw = A.read_exr(exr[0])
    site = A.label_map(glob.glob(os.path.join(rd, "*_site.txt"))[0])
    ground = A.label_map(glob.glob(os.path.join(rd, "*_ground.txt"))[0]) > 0
    rover = A.label_map(glob.glob(os.path.join(rd, "*_rover.txt"))[0]) > 0 if glob.glob(os.path.join(rd, "*_rover.txt")) else np.zeros_like(ground)
    syn_veg = site > 0
    rs = A.lab_stats(t.rgb, t.veg)
    ss = A.lab_stats(t.rgb, (~t.veg) & t.valid)
    g = A.fit_gain(raw, rs["L50"], syn_veg, wb=WB, ccm=ccm)
    soil = ground & ~syn_veg & ~rover
    lo, hi = 0.1, 3.0
    for _ in range(18):
        mid = np.sqrt(lo * hi)
        r = raw.copy(); r[soil] *= mid
        L = A.lab_stats(A.develop(r, g, wb=WB, ccm=ccm), soil)["L50"]
        lo, hi = (mid, hi) if L < ss["L50"] else (lo, mid)
    s = np.sqrt(lo * hi)
    r = raw.copy(); r[soil] *= s
    dev = A.develop(r, g, wb=WB, ccm=ccm)
    cmp = A.compare(t.rgb, t.veg, t.valid, dev, syn_veg, (ground | syn_veg) & ~rover)
    sites = fit["sites"]
    ious = [x.get("iou", 0.0) for x in sites]
    # scene IoU from the fit's own final raster, recomputed here against the real mask
    scene = json.load(open(os.path.join(work, "scene.json"))) if os.path.exists(os.path.join(work, "scene.json")) else None
    label = f"{tag.replace('_opt', '')}: {len(sites)} plants, per-plant IoU median {np.median(ious):.2f}"
    P.three_pane(t.rgb, dev, syn_veg, os.path.join(work, "three_pane.jpg"), width=2100, label=None)
    im = cv2.imread(os.path.join(work, "three_pane.jpg"))
    cv2.imwrite(os.path.join(REPORT, f"three_{tag}.jpg"), cv2.resize(im, (1500, int(im.shape[0] * 1500 / im.shape[1])), interpolation=cv2.INTER_AREA), [cv2.IMWRITE_JPEG_QUALITY, 78])
    row = dict(tag=tag, target=fit["target"], n_plants=len(sites), iou_median=float(np.median(ious)), iou_min=float(min(ious)), iou_max=float(max(ious)),
               gain=g, soil_scale=s, cover_real=t.cover, veg_frac_syn=float(syn_veg[t.valid].mean()),
               foliage=cmp["foliage"], soil=cmp["soil"], distance=cmp["distance"])
    json.dump(row, open(os.path.join(work, "appearance.json"), "w"), indent=1, default=float)
    summary.append(row)
    f, so = cmp["foliage"], cmp["soil"]
    print(f"{tag}: {len(sites)} plants, IoU median {np.median(ious):.3f}; cover real {t.cover:.3f} syn {row['veg_frac_syn']:.3f}; "
          f"foliage L*/a*/b* real {f['real']['L50']:.0f}/{f['real']['a50']:.0f}/{f['real']['b50']:.0f} syn {f['syn']['L50']:.0f}/{f['syn']['a50']:.0f}/{f['syn']['b50']:.0f}; "
          f"soil real {so['real']['L50']:.0f}/{so['real']['a50']:.0f}/{so['real']['b50']:.0f} syn {so['syn']['L50']:.0f}/{so['syn']['a50']:.0f}/{so['syn']['b50']:.0f}; distance {cmp['distance']:.1f}")
json.dump(summary, open(os.path.join(REPORT, "gallery.json"), "w"), indent=1, default=float)
