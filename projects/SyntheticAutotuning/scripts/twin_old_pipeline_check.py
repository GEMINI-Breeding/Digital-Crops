"""Does the Helios 1.3.49 image pipeline (Syn2Real_cowpea) preserve chroma while balancing? Measures the Syn2Real frames and
the real frames, and replays that pipeline -- median auto-exposure, response-area correction, gray-edge white balance (as
written, including its filter), sRGB -- on our raw baseline EXR next to the white-reference balance.
Foliage and soil are split by colour (CIELAB a* < -6 is foliage) in every image, rover pixels excluded, so all rows use one rule.
usage: twin_old_pipeline_check.py
"""
import glob
import os
import re
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import twin.appearance as A  # noqa: E402
import twin.real as R  # noqa: E402

HELIOS = "/group/bnbaileygrp/bnbailey/Helios"
rover = np.load(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "calib", "rover_mask.npy"))


def split_stats(rgb):
    lab = R.lab(rgb)
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    ok = ~rover if rover.shape == L.shape else np.ones(L.shape, bool)
    fol = ok & (a < -6) & (L > 10)
    soil = ok & ~(a < -6) & (L > 10)
    out = []
    for m in (fol, soil):
        aa, bb, ll = np.median(a[m]), np.median(b[m]), np.median(L[m])
        out.append((ll, aa, bb, np.hypot(aa, bb), m.mean()))
    return out


def response(label):
    txt = open(os.path.join(HELIOS, "plugins/radiation/spectral_data/camera_spectral_library.xml")).read()
    m = re.search(r'label="%s"\s*>(.*?)</globaldata_vec2>' % re.escape(label), txt, re.S)
    v = np.array(m.group(1).split(), float).reshape(-1, 2)
    return np.trapz(v[:, 1], v[:, 0])


def old_pipeline(raw):
    out = raw.astype(np.float64).copy()
    lum = 0.2126 * out[..., 0] + 0.7152 * out[..., 1] + 0.0722 * out[..., 2]
    out *= 0.18 / max(np.median(lum), 1e-6)
    integ = np.array([response(f"Basler_acA2500-20gc_{c}") for c in ("red", "green", "blue")])
    out *= integ.min() / integ
    # whiteBalanceGrayEdge(order 1, p 5) as written in 1.3.49: the /8 applies only to the subtracted column (or row)
    p = 5.0
    M = []
    for c in range(3):
        d = out[..., c]
        right = d[:-2, 2:] + 2 * d[1:-1, 2:] + d[2:, 2:]
        left = d[:-2, :-2] + 2 * d[1:-1, :-2] + d[2:, :-2]
        bottom = d[2:, :-2] + 2 * d[2:, 1:-1] + d[2:, 2:]
        top = d[:-2, :-2] + 2 * d[:-2, 1:-1] + d[:-2, 2:]
        dx = right - left / 8.0
        dy = bottom - top / 8.0
        M.append(np.sqrt(dx * dx + dy * dy))
    M = np.stack(M, -1)
    valid = (M > 0).any(-1)
    Mc = np.array([np.mean(M[..., c][valid] ** p) ** (1 / p) for c in range(3)])
    gray = Mc.mean() / Mc
    out *= gray
    total = (integ.min() / integ) * gray
    srgb = np.clip(np.where(out <= 0.0031308, 12.92 * out, 1.055 * np.clip(out, 0, None) ** (1 / 2.4) - 0.055), 0, 1)
    return (srgb * 255).astype(np.uint8), total / total[1]


def row(name, rgb, extra=""):
    (fl, fa, fb, fc, ff), (sl, sa, sb, sc, sf) = split_stats(rgb)
    print(f"{name:52s} foliage L {fl:3.0f} a {fa:4.0f} b {fb:4.0f} C {fc:3.0f} ({100*ff:4.1f}% px)   soil L {sl:3.0f} a {sa:4.0f} b {sb:4.0f} C {sc:3.0f} {extra}")


for f in sorted(glob.glob("/group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/twin_work/*_leaf/fit.json"))[:0]:
    pass
real = sorted(glob.glob(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "twin_work", "2023-06-27_Plot298-MAGIC226_leaf", "target_rgb*.png")))
import json  # noqa: E402
import twin.fit as F  # noqa: E402
tw = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "twin_work", "2023-06-27_Plot298-MAGIC226_leaf")
t = F.Target(json.load(open(os.path.join(tw, "fit.json")))["target"], tw)
row("real 2023-06-27 Plot298", t.rgb)
for fpath in sorted(glob.glob(os.path.join(HELIOS, "projects/Syn2Real_cowpea/frames/*.jpeg")))[:6]:
    row("Syn2Real " + os.path.basename(fpath), cv2.cvtColor(cv2.imread(fpath), cv2.COLOR_BGR2RGB))
for sub in ("render", "render_wbref_sunoff"):
    d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "twin_work", "baseline_2023-06-27", sub)
    raw = A.read_exr(glob.glob(os.path.join(d, "*_raw.exr"))[0])
    img, gains = old_pipeline(raw)
    row(f"baseline {sub}: 1.3.49 pipeline replayed", img[:, ::-1], f"gains {np.round(gains, 3)}")
    jpg = cv2.cvtColor(cv2.imread(glob.glob(os.path.join(d, "*_RGB.jpeg"))[0]), cv2.COLOR_BGR2RGB)
    row(f"baseline {sub}: Helios JPEG as rendered", jpg)
