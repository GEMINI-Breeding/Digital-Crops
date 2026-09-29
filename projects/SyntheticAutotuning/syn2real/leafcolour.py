"""Leaf-to-leaf colour variation, measured the same way on both domains.

Whole-tile pixel spread conflates three things: leaf-to-leaf pigment differences, within-leaf
shading, and shadow between leaves. Only the first is a property of the plant model. Taking the
MEDIAN over leaf-sized windows and then the spread of those medians isolates it -- shading averages
out inside a window, and windows that are not essentially all foliage are dropped.

Measured this way the real canopy spans 8.73 units of CIELAB a* between its 10th and 90th
percentiles and a single-spectrum synthetic canopy spans 4.14, with the deficit almost entirely at
the dark end: real p10 -27.5 against a synthetic -23.0, while the pale ends agree to 0.03. Lightness
is much closer -- 15.8 against 13.6 within a tile -- so chroma, not brightness, is the axis that
distinguishes them.
"""

from __future__ import annotations

import glob
import os

import numpy as np

#: Window side in tile pixels. About half a cowpea leaflet, which is ~110 tile px across, so a
#: window sits inside one leaf rather than straddling several.
WINDOW_PX = 55

#: Foliage threshold on CIELAB a*. Deliberately stricter than the -5 used elsewhere: this soil
#: renders at a* -5.9, and at the looser threshold it enters the foliage statistics.
A_FOLIAGE = -12.0

#: Fraction of a window that must be foliage for it to count.
MIN_FOLIAGE_FRACTION = 0.80

#: Real reference, measured over 120 tiles of the 263-tile set. Recomputed when the window
#: statistic changed from median to mean; the earlier integer-quantised values were
#: a_p10 -28.0, a_p50 -23.0, a_p90 -19.0, a_spread 9.0.
REAL = dict(a_p10=-27.543, a_p50=-22.416, a_p90=-18.814, a_spread=8.729,
            L_spread_within_tile=15.781, L_p50=49.787)


def tile_patches(path):
    """Per-window median L* and a* for one tile, or None if too little foliage."""
    import cv2

    bgr = cv2.imread(path)
    if bgr is None:
        raise IOError(f"cannot read {path}")
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    L, A = lab[:, :, 0] * 100 / 255, lab[:, :, 1] - 128
    foliage = A < A_FOLIAGE
    Ls, As = [], []
    height, width = L.shape
    for y in range(0, height - WINDOW_PX + 1, WINDOW_PX):
        for x in range(0, width - WINDOW_PX + 1, WINDOW_PX):
            mask = foliage[y:y + WINDOW_PX, x:x + WINDOW_PX]
            if mask.mean() < MIN_FOLIAGE_FRACTION:
                continue
            # Mean, not median. OpenCV returns uint8 Lab, so a* is integer-valued and a median of
            # integers is an integer: the statistic quantised to 1 a* unit and could not separate
            # configurations whose renders demonstrably differed. The 80% foliage gate above is what
            # makes a mean safe here -- it is the gate, not the median, that keeps soil and shadow
            # out of the window.
            Ls.append(float(L[y:y + WINDOW_PX, x:x + WINDOW_PX][mask].mean()))
            As.append(float(A[y:y + WINDOW_PX, x:x + WINDOW_PX][mask].mean()))
    if len(Ls) < 12:
        return None
    return np.array(Ls), np.array(As)


def dataset_patches(tile_dir, limit=None, seed=0):
    """Pooled per-window medians over a tiled dataset, plus the within-tile lightness spread."""
    files = sorted(glob.glob(os.path.join(tile_dir, "images", "*.jpg")) +
                   glob.glob(os.path.join(tile_dir, "images", "*.jpeg")))
    if not files:
        raise FileNotFoundError(f"no tiles under {tile_dir}/images")
    if limit is not None and limit < len(files):
        rng = np.random.default_rng(seed)
        files = [files[i] for i in rng.choice(len(files), limit, replace=False)]
    all_L, all_A, per_tile_L_spread = [], [], []
    for path in files:
        patches = tile_patches(path)
        if patches is None:
            continue
        Ls, As = patches
        all_L.append(Ls)
        all_A.append(As)
        per_tile_L_spread.append(np.percentile(Ls, 90) - np.percentile(Ls, 10))
    if not all_L:
        raise ValueError(f"no tile under {tile_dir} had enough foliage to measure")
    return np.concatenate(all_L), np.concatenate(all_A), np.array(per_tile_L_spread)


def summarise(tile_dir, limit=None, seed=0):
    """The comparison statistics, keyed to match `REAL`."""
    L, A, tile_spread = dataset_patches(tile_dir, limit=limit, seed=seed)
    return dict(a_p10=float(np.percentile(A, 10)), a_p50=float(np.median(A)),
                a_p90=float(np.percentile(A, 90)),
                a_spread=float(np.percentile(A, 90) - np.percentile(A, 10)),
                L_spread_within_tile=float(np.median(tile_spread)),
                L_p50=float(np.median(L)), n_windows=int(len(A)))
