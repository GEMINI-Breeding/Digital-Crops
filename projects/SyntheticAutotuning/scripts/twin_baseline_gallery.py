"""Four-pane figures and numbers: real | naive baseline | tuned twin | twin masks on real.

The baseline image is the renderer's own JPEG (stock auto exposure and white balance), put into
the label maps' frame by the flip that best correlates its luminance with the raw EXR. The twin
image is developed exactly as in twin_develop_gallery.py. For both, against the real frame:
scene vegetation IoU (rover excluded), cover, leaflet half-width, foliage and soil L*/a*/b*.
usage: twin_baseline_gallery.py [--baseline render_folder] [--twin suffix] [--fit suffix]
  --baseline  folder under twin_work/baseline_<date> (default "render"; e.g. render_current_sunoff)
  --twin      twin workdir suffix whose render_soil/ is shown (default "_leaf"; e.g. "_colour_final")
  --fit       workdir suffix holding fit.json (default: the --twin suffix)
"""
import argparse
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
import twin.real as R  # noqa: E402
from twin.stage1 import leaflet_stats  # noqa: E402

FRAMES = ["2023-06-20_Plot286-MAGIC083", "2023-06-20_Plot201-MAGIC262", "2023-06-27_Plot286-MAGIC083", "2023-06-27_Plot298-MAGIC226", "2023-07-03_Plot286-MAGIC083"]
WB = (1.563, 1.0, 1.596)
ccm = A.CP.read_ccm(os.path.join(TR.PROJECT, "calib", "ccm_camA_20230728.xml"))
rover_tight = np.load(os.path.join(TR.PROJECT, "calib", "rover_mask.npy"))
REPORT = os.path.join(TR.PROJECT, "twin_work", "report")
MM_PER_PX = 1.55 / R.FX * 1000.0


def orient_jpeg(jpg, raw):
    """The flip of the renderer's JPEG that best matches the EXR (label-map frame)."""
    lum_raw = np.log1p(1e4 * (0.2126 * raw[..., 0] + 0.7152 * raw[..., 1] + 0.0722 * raw[..., 2]))
    small = cv2.resize(lum_raw.astype(np.float32), (324, 256), interpolation=cv2.INTER_AREA).ravel()
    best = None
    for name, f in (("id", lambda x: x), ("flipx", lambda x: x[:, ::-1]), ("flipy", lambda x: x[::-1]), ("flipxy", lambda x: x[::-1, ::-1])):
        cand = f(jpg)
        g = cv2.resize(cv2.cvtColor(cand, cv2.COLOR_RGB2GRAY).astype(np.float32), (324, 256), interpolation=cv2.INTER_AREA).ravel()
        r = float(np.corrcoef(g, small)[0, 1])
        if best is None or r > best[0]:
            best = (r, name, np.ascontiguousarray(cand))
    return best


def scene_metrics(real_t, img, veg, valid):
    inter = (veg & real_t.veg & valid).sum(); union = ((veg | real_t.veg) & valid).sum()
    rw, rn = leaflet_stats(real_t.veg & valid, min_r=12, window=61)
    sw, sn = leaflet_stats(veg & valid, min_r=12, window=61)
    fo = A.lab_stats(img, veg & valid); so = A.lab_stats(img, (~veg) & valid)
    return dict(iou=float(inter / max(union, 1)), cover=float(veg[valid].mean()), leaflet_mm=float(np.median(sw) * MM_PER_PX) if len(sw) else 0.0,
                leaflets=int(sn), foliage=fo, soil=so), dict(leaflet_mm=float(np.median(rw) * MM_PER_PX), leaflets=int(rn))


ap = argparse.ArgumentParser()
ap.add_argument("--baseline", default="render")
ap.add_argument("--twin", default="_leaf")
ap.add_argument("--fit", default=None)
args = ap.parse_args()

rows = []
for fr in FRAMES:
    date = fr[:10]
    tw = os.path.join(TR.PROJECT, "twin_work", fr + args.twin)
    fw = os.path.join(TR.PROJECT, "twin_work", fr + (args.fit or args.twin))
    bw = os.path.join(TR.PROJECT, "twin_work", "baseline_" + date)
    fit = json.load(open(os.path.join(fw, "fit.json")))
    t = F.Target(fit["target"], fw)
    valid = ~rover_tight
    # tuned twin
    rd = os.path.join(tw, "render_soil")
    raw = A.read_exr(glob.glob(os.path.join(rd, "*_raw.exr"))[0])
    tveg = A.label_map(glob.glob(os.path.join(rd, "*_site.txt"))[0]) > 0
    g = A.fit_gain(raw, A.lab_stats(t.rgb, t.veg)["L50"], tveg, wb=WB, ccm=ccm)
    twin_img = A.develop(raw, g, wb=WB, ccm=ccm)
    # naive baseline
    bd = os.path.join(bw, args.baseline)
    braw = A.read_exr(glob.glob(os.path.join(bd, "*_raw.exr"))[0])
    bjpg = cv2.cvtColor(cv2.imread(glob.glob(os.path.join(bd, "*_RGB.jpeg"))[0]), cv2.COLOR_BGR2RGB)
    corr, flip, base_img = orient_jpeg(bjpg, braw)
    bveg = A.label_map(glob.glob(os.path.join(bd, "*_site.txt"))[0]) > 0
    mt, real_leaf = scene_metrics(t, twin_img, tveg, valid)
    mb, _ = scene_metrics(t, base_img, bveg, valid)
    fo_r = A.lab_stats(t.rgb, t.veg & valid); so_r = A.lab_stats(t.rgb, (~t.veg) & valid)
    row = dict(frame=fr, twin_render=args.twin, baseline_render=args.baseline, jpeg_flip=flip, jpeg_corr=corr, real=dict(cover=float(t.veg[valid].mean()), foliage=fo_r, soil=so_r, **real_leaf), baseline=mb, twin=mt)
    rows.append(row)
    P.four_pane(t.rgb, base_img, twin_img, tveg, os.path.join(tw, "four_pane.jpg"), width=2400)
    im = cv2.imread(os.path.join(tw, "four_pane.jpg"))
    cv2.imwrite(os.path.join(REPORT, f"four_{fr}.jpg"), cv2.resize(im, (1600, int(im.shape[0] * 1600 / im.shape[1])), interpolation=cv2.INTER_AREA), [cv2.IMWRITE_JPEG_QUALITY, 78])
    f = lambda s: f"{s['L50']:.0f}/{s['a50']:.0f}/{s['b50']:.0f}"
    print(f"{fr}: JPEG {flip} (r {corr:.2f})")
    print(f"   real     cover {row['real']['cover']:.3f}  leaflet {real_leaf['leaflet_mm']:.0f} mm / {real_leaf['leaflets']}  foliage {f(fo_r)}  soil {f(so_r)}")
    for k in ("baseline", "twin"):
        m = row[k]
        print(f"   {k:8s} cover {m['cover']:.3f}  IoU {m['iou']:.3f}  leaflet {m['leaflet_mm']:.0f} mm / {m['leaflets']}  foliage {f(m['foliage'])}  soil {f(m['soil'])}")
json.dump(rows, open(os.path.join(REPORT, "baseline_vs_twin.json"), "w"), indent=1, default=float)
