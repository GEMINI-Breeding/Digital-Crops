"""Stage 5: appearance, with the geometry frozen.

The ray tracer writes raw linear radiance (EXR) for a scene; everything downstream of that --
white balance, colour matrix, gain, tone curve, saturation -- is a per-pixel function that the
`syn2real.camera_pipeline` replica evaluates in a second. So the post chain is fitted against
the real frame on the CPU from one EXR, and only the scene-side appearance parameters (light
flux and diffuse fill, soil reflectance, leaf pigments) need a new render.

The comparison is masked and statistical, never pixel-wise: foliage and soil pixels are taken
from the real vegetation mask and from the rendered label maps respectively, and their CIELAB
distributions (median L*, a*, b*, and the 10-90 spread of L*) are compared. A per-plant match of
leaf poses is stage 6's job; at stage 5 the layout is only right to within a leaf.
"""
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real import camera_pipeline as CP  # noqa: E402

from . import real as R  # noqa: E402

#: The camera's own white balance from the rover configuration (camA.pbtxt), R:G:B.
CAMERA_WB = (1.53125, 1.0, 1.921875)


def read_exr(path):
    return CP.read_raw_exr(path)


def label_map(path):
    """A `writePrimitiveDataLabelMap` text map as an int array, NaN -> 0."""
    a = np.loadtxt(path)
    return np.where(np.isnan(a), 0, a).astype(np.int32)


def develop(raw, gain, wb=CAMERA_WB, ccm=None, ccm_strength=1.0, knee=0.55, saturation=1.0, black_level=0.0, blur_sigma=0.0, noise_sigma=0.0, jpeg_quality=None):
    """Raw linear radiance -> display RGB uint8 through the replica pipeline."""
    out = CP.process(raw, exposure=float(gain), white_balance=tuple(wb), ccm=ccm, ccm_strength=ccm_strength,
                     highlight_knee=knee, saturation=saturation, black_level=black_level, blur_sigma=blur_sigma,
                     noise_sigma=noise_sigma, jpeg_quality=jpeg_quality)
    return (np.clip(out, 0, 1) * 255).astype(np.uint8)


def lab_stats(rgb, mask):
    lab = R.lab(rgb)
    m = mask & np.isfinite(lab[..., 0])
    if m.sum() < 100:
        return None
    L, a, b = lab[..., 0][m], lab[..., 1][m], lab[..., 2][m]
    return dict(n=int(m.sum()), L50=float(np.median(L)), a50=float(np.median(a)), b50=float(np.median(b)),
                L10=float(np.percentile(L, 10)), L90=float(np.percentile(L, 90)),
                a10=float(np.percentile(a, 10)), a90=float(np.percentile(a, 90)))


def compare(real_rgb, real_veg, real_valid, syn_rgb, syn_veg, syn_valid):
    """Foliage and soil colour statistics, real against synthetic, plus a scalar distance."""
    out = {}
    for name, rm, sm in (("foliage", real_veg, syn_veg), ("soil", ~real_veg, ~syn_veg)):
        a = lab_stats(real_rgb, rm & real_valid)
        b = lab_stats(syn_rgb, sm & syn_valid)
        out[name] = dict(real=a, syn=b)
    # distance: L*, a*, b* medians and the L* spread, in units that make 1 = "clearly visible"
    d = 0.0
    for name, w in (("foliage", 1.0), ("soil", 0.5)):
        a, b = out[name]["real"], out[name]["syn"]
        if a is None or b is None:
            d += 4.0 * w
            continue
        d += w * (abs(a["L50"] - b["L50"]) / 5.0 + abs(a["a50"] - b["a50"]) / 3.0 + abs(a["b50"] - b["b50"]) / 4.0
                  + abs((a["L90"] - a["L10"]) - (b["L90"] - b["L10"])) / 6.0)
    out["distance"] = d
    return out


def fit_gain(raw, real_L50, veg_mask, wb=CAMERA_WB, ccm=None, **kw):
    """Gain that puts the developed foliage median L* at the real value (geometric bisection)."""
    lo, hi = 1.0, 1e6
    for _ in range(28):
        g = np.sqrt(lo * hi)
        rgb = develop(raw, g, wb=wb, ccm=ccm, **kw)
        s = lab_stats(rgb, veg_mask)
        if s is None or s["L50"] < real_L50:
            lo = g
        else:
            hi = g
    return float(np.sqrt(lo * hi))


def orient_like_raster(img):
    """The EXR and the label maps share the rasterizer's frame; the renderer's JPEG is flipped
    on both axes relative to its buffer and therefore vertically relative to those maps."""
    return img
