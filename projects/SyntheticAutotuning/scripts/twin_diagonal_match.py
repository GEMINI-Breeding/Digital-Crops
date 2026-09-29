"""Which per-channel gains on our raw baseline render reproduce the Syn2Real_cowpea colours, and what foliage chroma comes
with them? White balance of any kind (gray world, gray edge, white reference) is one gain per channel, so this bounds what
the old pipeline could have done. Masks: site map for foliage, non-vegetation outside the rover for soil.
usage: twin_diagonal_match.py
"""
import glob
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import twin.appearance as A  # noqa: E402
import twin.real as R  # noqa: E402

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
rover = np.load(os.path.join(PROJECT, "calib", "rover_mask.npy"))
d = os.path.join(PROJECT, "twin_work", "baseline_2023-06-27", "render_wbref_sunoff")
raw = A.read_exr(glob.glob(os.path.join(d, "*_raw.exr"))[0]).astype(np.float32)
veg = A.label_map(glob.glob(os.path.join(d, "*_site.txt"))[0]) > 0
small = lambda x, interp: cv2.resize(x, (648, 512), interpolation=interp)
raw_s = small(raw, cv2.INTER_AREA)
fol = small(veg.astype(np.uint8), cv2.INTER_NEAREST) > 0
soil = (~fol) & ~(small(rover.astype(np.uint8), cv2.INTER_NEAREST) > 0)


def develop(gains):
    lin = raw_s * np.array(gains, np.float32)
    lum = 0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]
    lin = lin * (0.18 / np.median(lum[soil]))
    srgb = np.clip(np.where(lin <= 0.0031308, 12.92 * lin, 1.055 * np.clip(lin, 0, None) ** (1 / 2.4) - 0.055), 0, 1)
    lab = R.lab((srgb * 255).astype(np.uint8))
    f = [float(np.median(lab[..., i][fol])) for i in (1, 2)]
    s = [float(np.median(lab[..., i][soil])) for i in (1, 2)]
    return f, s


target_soil = (2.0, 15.0)   # Syn2Real frames, median soil a*, b*
best = None
for gr in np.arange(1.0, 2.61, 0.05):
    for gb in np.arange(0.6, 2.01, 0.05):
        f, s = develop((gr, 1.0, gb))
        err = np.hypot(s[0] - target_soil[0], s[1] - target_soil[1])
        if best is None or err < best[0]:
            best = (err, gr, gb, f, s)
for name, g in (("white-reference (neutral white card)", (1.559, 1.0, 1.591)), ("best match to Syn2Real soil", (best[1], 1.0, best[2]))):
    f, s = develop(g)
    print(f"{name:40s} gains {np.round(g, 2)}  soil a* {s[0]:5.1f} b* {s[1]:5.1f}   foliage a* {f[0]:5.1f} b* {f[1]:5.1f} C* {np.hypot(*f):5.1f}")
# what a white card looks like under the best-match gains: the raw white card under the LEDs is 0.622 / 1 / 0.605
card = np.array([0.622, 1.0, 0.605]) * np.array([best[1], 1.0, best[2]])
print("white card under those gains, R/G/B relative:", np.round(card / card[1], 2))


# Same colour-threshold masks as twin_old_pipeline_check.py uses for the Syn2Real frames, for a like-for-like comparison
def threshold_stats(gains):
    lin = raw_s * np.array(gains, np.float32)
    lum = 0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]
    lin = lin * (0.18 / np.median(lum[soil]))
    srgb = np.clip(np.where(lin <= 0.0031308, 12.92 * lin, 1.055 * np.clip(lin, 0, None) ** (1 / 2.4) - 0.055), 0, 1)
    lab = R.lab((srgb * 255).astype(np.uint8))
    ok = ~(small(rover.astype(np.uint8), cv2.INTER_NEAREST) > 0)
    m = ok & (lab[..., 1] < -6) & (lab[..., 0] > 10)
    a, b = float(np.median(lab[..., 1][m])), float(np.median(lab[..., 2][m]))
    return a, b, float(np.hypot(a, b)), float(m.mean())


for name, g in (("white-reference, threshold mask", (1.559, 1.0, 1.591)), ("best match, threshold mask", (best[1], 1.0, best[2]))):
    a, b, c, frac = threshold_stats(g)
    print(f"{name:40s} foliage a* {a:5.1f} b* {b:5.1f} C* {c:5.1f} ({100 * frac:.1f}% px)")
