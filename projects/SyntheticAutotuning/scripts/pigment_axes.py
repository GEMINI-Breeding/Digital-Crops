"""Which PROSPECT pigment moves leaf CHROMA, and which only moves lightness?

The nitrogen model gave the canopy a chlorophyll spread of 19.6-84 ug/cm2 and the rendered a* spread
did not move at all, while L* spread rose from 13.6 to 16.7. That says chlorophyll density controls
how dark a leaf renders, not how green it is -- but it was measured through a whole canopy, so it
could equally have been shadowing or the colour matrix compressing chroma.

This settles it without rendering. PROSPECT spectra go through the real camera's spectral response
and the same colour matrix and tone curve the images get, and the resulting L* and a* are regressed
on the six pigment parameters. If chlorophyll genuinely cannot move a*, the fix is a different
pigment; if it can, the compression happens in the canopy and no pigment choice will help.

Also reports whether the real leaf a* range is reachable AT ALL through this camera, which decides
whether the target is a modelling problem or an unreachable one.
"""
import os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real.prospect_fit import load_grid, camera_rgb
from syn2real.spectra import load_spectra
from syn2real import camera_pipeline as cp
from syn2real.leafcolour import REAL

HELIOS = "/group/bnbaileygrp/bnbailey/Helios/"
GRID = "spectra/pigment_grid.txt"
NAMES = ["Cab", "Car", "Cant", "N_layers", "Cw", "Cdm"]

params, R, T, wl = load_grid(GRID)
cam = load_spectra(HELIOS + "plugins/radiation/spectral_data/camera_spectral_library.xml",
                   want={"Basler_acA2500-20gc_red", "Basler_acA2500-20gc_green",
                         "Basler_acA2500-20gc_blue"})
light = load_spectra(HELIOS + "plugins/radiation/spectral_data/light_spectral_library.xml",
                     want={"CREE_XLamp_XHP70p2_6500K"})["CREE_XLamp_XHP70p2_6500K"]
q = (cam["Basler_acA2500-20gc_red"], cam["Basler_acA2500-20gc_green"],
     cam["Basler_acA2500-20gc_blue"])

linear = camera_rgb(R, wl, light, q)                     # n x 3, linear camera RGB

# Through the SAME post-processing the images get. Exposure is a camera property, not a leaf one, so
# a single gain is chosen to put the population median at the real foliage lightness; without it the
# whole cloud sits at an arbitrary level and L* comparisons are meaningless.
ccm = cp.read_ccm("calib/ccm_camA_20230728.xml")
import cv2


def to_lab(lin_rgb, gain):
    img = np.asarray(lin_rgb, np.float32)[None, :, :] * gain
    out = cp.apply_ccm(img, ccm, strength=1.0)
    out = cp.tone_curve(out, black_level=0.0, highlight_knee=0.55)
    out = cp.lin_to_srgb(out)
    bgr = np.clip(out[:, :, ::-1] * 255, 0, 255).astype(np.uint8)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    return lab[0, :, 0] * 100 / 255, lab[0, :, 1] - 128


lo, hi = 1e-3, 1e3
for _ in range(40):
    mid = np.sqrt(lo * hi)
    L, _a = to_lab(linear, mid)
    if np.median(L) < REAL["L_p50"]:
        lo = mid
    else:
        hi = mid
gain = np.sqrt(lo * hi)
L, A = to_lab(linear, gain)
print(f"gain {gain:.4g} puts median L* at {np.median(L):.2f} (real foliage {REAL['L_p50']:.2f})\n")

print(f"{'pigment':>10} {'range':>16} {'d a*/decile':>12} {'d L*/decile':>12} {'|corr a*|':>10}")
for i, name in enumerate(NAMES):
    x = params[:, i]
    lo_q, hi_q = np.percentile(x, 10), np.percentile(x, 90)
    low, high = x <= lo_q, x >= hi_q
    da = np.median(A[high]) - np.median(A[low])
    dL = np.median(L[high]) - np.median(L[low])
    corr = abs(np.corrcoef(x, A)[0, 1])
    print(f"{name:>10} {lo_q:7.2f}-{hi_q:7.2f} {da:12.2f} {dL:12.2f} {corr:10.3f}")

print(f"\nreachable a* across the whole grid: {np.percentile(A,1):.2f} to {np.percentile(A,99):.2f}")
print(f"real leaf a* needed:                {REAL['a_p10']:.2f} to {REAL['a_p90']:.2f} "
      f"(spread {REAL['a_spread']:.2f})")

# Holding lightness fixed, how much a* is available? This is the quantity that matters: the canopy
# median must not move, so only variation orthogonal to L* is usable.
band = np.abs(L - np.median(L)) < 2.0
print(f"\nwithin +/-2 L* of the median ({band.sum()} of {len(L)} spectra):")
print(f"  a* spans {np.percentile(A[band],10):.2f} to {np.percentile(A[band],90):.2f} "
      f"(spread {np.percentile(A[band],90)-np.percentile(A[band],10):.2f})")
for i, name in enumerate(NAMES):
    c = np.corrcoef(params[band, i], A[band])[0, 1]
    print(f"    {name:>9} correlates {c:+.3f} with a* at fixed lightness")
