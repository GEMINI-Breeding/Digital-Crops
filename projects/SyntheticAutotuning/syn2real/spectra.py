"""Predict rendered leaf colour directly from the spectral inputs.

The Tier-0 report's single largest signal is a foliage colour gap (hue 100 deg
vs 84, saturation 0.39 vs 0.55). That gap can originate in either
  (a) the PHYSICS  -- measured leaf spectra x light spectrum x camera response, or
  (b) the POST-PROCESSING -- white balance, exposure, gamma, saturation.
This module evaluates (a) in closed form so we can tell which, without spending
GPU hours on render sweeps.
"""
import re
import numpy as np


def load_spectra(path, want=None):
    """Parse Helios <globaldata_vec2 label="..."> wavelength/value blocks."""
    txt = open(path).read()
    out = {}
    for m in re.finditer(r'<globaldata_vec2\s+label="([^"]+)"\s*>(.*?)</globaldata_vec2>',
                         txt, re.S):
        label = m.group(1)
        if want is not None and label not in want:
            continue
        vals = np.fromstring(m.group(2).replace('\n', ' '), sep=' ')
        out[label] = vals.reshape(-1, 2)
    return out


def resample(spec, grid):
    return np.interp(grid, spec[:, 0], spec[:, 1], left=0.0, right=0.0)


def predict_rgb(reflectance, light, qr, qg, qb, grid, white_balance=True):
    """Camera RGB for a surface of given reflectance under `light`.

    Normalizing by the response to a perfect white diffuser under the same
    light is exactly what Helios' 'auto' white balance does, so this is the
    renderer's own convention.
    """
    R = resample(reflectance, grid)
    L = resample(light, grid)
    Q = np.stack([resample(q, grid) for q in (qr, qg, qb)])
    sig = (L * R * Q).sum(1)
    if white_balance:
        wht = (L * Q).sum(1)
        sig = sig / np.maximum(wht, 1e-12)
    return sig


def srgb_gamma(x):
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def to_hsv(rgb01):
    import cv2
    a = (np.clip(rgb01, 0, 1) * 255).astype(np.uint8).reshape(1, 1, 3)
    h, s, v = cv2.cvtColor(a, cv2.COLOR_RGB2HSV)[0, 0]
    return float(h) * 2, float(s) / 255, float(v) / 255
