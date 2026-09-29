"""Camera white balance comparison: real | baseline, previous auto white balance | baseline, white-reference auto
white balance | tuned twin (developed from the raw EXR with the fitted colour chain, for reference).

The two baseline panes are the renderer's own JPEGs (Helios auto exposure and auto white balance, no colour
matrix): render/ from the previous Helios, render_wbref/ from the white-reference balance. Also measures the
grey card under the rig LEDs (twin_work/wbcheck) in the JPEG with the camera white balance off, the previous
auto and the white-reference auto.
usage: twin_wbref_gallery.py
"""
import glob
import json
import os
import re
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import twin.appearance as A  # noqa: E402
import twin.fit as F  # noqa: E402
import twin.panels as P  # noqa: E402
import twin.raster as TR  # noqa: E402


def orient_jpeg(jpg, raw):
    """The flip of the renderer's JPEG that best matches the EXR (label-map frame). Same as twin_baseline_gallery.py."""
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

FRAMES = ["2023-06-20_Plot286-MAGIC083", "2023-06-20_Plot201-MAGIC262", "2023-06-27_Plot286-MAGIC083", "2023-06-27_Plot298-MAGIC226", "2023-07-03_Plot286-MAGIC083"]
WB = (1.563, 1.0, 1.596)
ccm = A.CP.read_ccm(os.path.join(TR.PROJECT, "calib", "ccm_camA_20230728.xml"))
rover_tight = np.load(os.path.join(TR.PROJECT, "calib", "rover_mask.npy"))
WORK = os.path.join(TR.PROJECT, "twin_work")
OUT = os.path.join(WORK, "report", "wbref")
os.makedirs(OUT, exist_ok=True)


def lab(img, mask):
    s = A.lab_stats(img, mask)
    return None if s is None else [round(s["L50"], 1), round(s["a50"], 1), round(s["b50"], 1)]


def mean_srgb(img, mask):
    return [int(round(v)) for v in img[mask].reshape(-1, 3).mean(axis=0)]


result = dict(grey_card={}, frames=[])

# Grey card under the rig LEDs
for name, folder in (("off", "greypatch_wb_off"), ("previous auto", "greypatch_wb_auto"), ("white-reference auto", "greypatch_wbref")):
    d = os.path.join(WORK, "wbcheck", folder)
    raw = A.read_exr(glob.glob(os.path.join(d, "*_raw.exr"))[0])
    jpg = cv2.cvtColor(cv2.imread(glob.glob(os.path.join(d, "*_RGB.jpeg"))[0]), cv2.COLOR_BGR2RGB)
    _, flip, img = orient_jpeg(jpg, raw)
    patch = A.label_map(glob.glob(os.path.join(d, "*_patch.txt"))[0]) > 0
    patch = cv2.erode(patch.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    patch = cv2.resize(patch.astype(np.uint8), (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
    card = mean_srgb(img, patch)
    result["grey_card"][name] = dict(srgb=card, lab=lab(img, patch))
    print(f"grey card, {name:22s} sRGB {card}  Lab {lab(img, patch)}")
    ys, xs = np.nonzero(patch)
    cy, cx, h = int(ys.mean()), int(xs.mean()), 90
    crop = img[max(0, cy - h):cy + h, max(0, cx - int(1.3 * h)):cx + int(1.3 * h)]
    cv2.imwrite(os.path.join(OUT, f"card_{folder}.jpg"), cv2.cvtColor(crop, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])

def lin(u8):
    c = u8.astype(np.float64) / 255
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def applied_gains(img, raw):
    """White balance gains the renderer applied, from its JPEG against the raw EXR, normalized on green."""
    m = (img.max(axis=2) < 240) & (img.min(axis=2) > 20) & (raw.min(axis=2) > 0)
    L = lin(img)
    g = np.array([np.median(L[..., c][m] / raw[..., c][m]) for c in range(3)])
    return [round(float(v), 3) for v in g / g[1]]


def labelled(img, text, w, h):
    pane = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    cv2.putText(pane, text, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3)
    cv2.putText(pane, text, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    return pane


# Renders made with the fixed specular_scale handling and the white-reference white balance. The previous white balance no
# longer exists in Helios; it is recomputed from the same raw EXR with its fixed factors (see previous_white_balance()).
RENDERS = (("wbref", "render_fixed_sunconf", "white-reference auto WB"), ("wbref_sunspec", "render_fixed_sunspec", "white-reference WB, sun with spectrum"),
           ("wbref_sunoff", "render_fixed_sunoff", "white-reference WB, sun off"))


def response_area_factors():
    """The previous auto white balance: each channel scaled by the largest response area over its own (trapezoid over the response samples)."""
    txt = open(os.path.join(TR.PROJECT, "..", "..", "plugins", "radiation", "spectral_data", "camera_spectral_library.xml")).read()
    areas = []
    for c in ("red", "green", "blue"):
        m = re.search(r'<globaldata_vec2\s+label="Basler_acA2500-20gc_%s"\s*>(.*?)</globaldata_vec2>' % c, txt, re.S)
        v = np.array(m.group(1).split(), float).reshape(-1, 2)
        areas.append(float(np.sum(0.5 * (v[1:, 1] + v[:-1, 1]) * np.diff(v[:, 0]))))
    areas = np.array(areas)
    return areas.max() / areas


OLD_FACTORS = response_area_factors()


def previous_white_balance(jpg_img, raw):
    """The renderer's JPEG as it would have come out with the previous white balance: raw x exposure gain x the old factors, sRGB encoded.

    Exposure is applied before white balance, and the white-reference balance leaves green at unit gain in these scenes, so the exposure gain is the
    green channel's JPEG-to-raw ratio.
    """
    m = (jpg_img.max(axis=2) < 240) & (jpg_img.min(axis=2) > 20) & (raw.min(axis=2) > 0)
    k = np.median(lin(jpg_img)[..., 1][m] / raw[..., 1][m])
    out = np.clip(raw * k * OLD_FACTORS, 0, 1)
    srgb = np.where(out <= 0.0031308, 12.92 * out, 1.055 * out ** (1 / 2.4) - 0.055)
    return (np.clip(srgb, 0, 1) * 255 + 0.5).astype(np.uint8)

for fr in FRAMES:
    date = fr[:10]
    tw = os.path.join(WORK, fr + "_leaf")
    bw = os.path.join(WORK, "baseline_" + date)
    fit = json.load(open(os.path.join(tw, "fit.json")))
    t = F.Target(fit["target"], tw)
    valid = ~rover_tight

    rd = os.path.join(tw, "render_soil")
    raw = A.read_exr(glob.glob(os.path.join(rd, "*_raw.exr"))[0])
    tveg = A.label_map(glob.glob(os.path.join(rd, "*_site.txt"))[0]) > 0
    g = A.fit_gain(raw, A.lab_stats(t.rgb, t.veg)["L50"], tveg, wb=WB, ccm=ccm)
    twin_img = A.develop(raw, g, wb=WB, ccm=ccm)

    panes = {}
    row = dict(frame=fr, real=dict(foliage=lab(t.rgb, t.veg & valid), soil=lab(t.rgb, (~t.veg) & valid)))
    for key, sub, _ in RENDERS:
        bd = os.path.join(bw, sub)
        braw = A.read_exr(glob.glob(os.path.join(bd, "*_raw.exr"))[0]).astype(np.float64)
        bjpg = cv2.cvtColor(cv2.imread(glob.glob(os.path.join(bd, "*_RGB.jpeg"))[0]), cv2.COLOR_BGR2RGB)
        _, _, img = orient_jpeg(bjpg, braw)
        bveg = A.label_map(glob.glob(os.path.join(bd, "*_site.txt"))[0]) > 0
        panes[key] = img
        row[key] = dict(gains=applied_gains(img, braw), foliage=lab(img, bveg & valid), soil=lab(img, (~bveg) & valid))
        if key == "wbref":
            prev = previous_white_balance(img, braw)
            panes["previous"] = prev
            row["previous"] = dict(gains=applied_gains(prev, braw), foliage=lab(prev, bveg & valid), soil=lab(prev, (~bveg) & valid))
    row["twin"] = dict(foliage=lab(twin_img, tveg & valid), soil=lab(twin_img, (~tveg) & valid))
    result["frames"].append(row)

    w = 760
    h = int(t.rgb.shape[0] * w / t.rgb.shape[1])
    top = np.concatenate([labelled(t.rgb, "real", w, h), labelled(panes["previous"], "baseline: previous auto WB (recomputed)", w, h), labelled(panes["wbref"], "baseline: white-reference auto WB", w, h)], axis=1)
    bottom = np.concatenate([labelled(twin_img, "tuned twin (fitted colour chain)", w, h), labelled(panes["wbref_sunspec"], "white-reference WB, sun given a spectrum", w, h),
                             labelled(panes["wbref_sunoff"], "white-reference WB, sun off", w, h)], axis=1)
    sheet = np.concatenate([top, bottom], axis=0)
    cv2.imwrite(os.path.join(OUT, f"wb_{fr}.jpg"), cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 82])
    print(fr)
    for k in ("real", "previous") + tuple(r[0] for r in RENDERS) + ("twin",):
        extra = f"  gains {row[k]['gains']}" if "gains" in row[k] else ""
        print(f"   {k:14s} foliage Lab {row[k]['foliage']}  soil {row[k]['soil']}{extra}")

json.dump(result, open(os.path.join(OUT, "wbref.json"), "w"), indent=1)
