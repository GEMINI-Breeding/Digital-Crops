"""Geometric metrics: how big are the structures in the image, in pixels.

The harness measured flower geometry (from the labels) and camera appearance,
but leaf and canopy geometry only through a texture correlation length, which is
a weak proxy -- it is pulled around by blur, noise and soil-patch structure.

Granulometry measures it directly. Opening the image with a disc of radius r
removes every bright structure narrower than 2r; the drop in total intensity
between r and r+1 is therefore the amount of image "made of" structures of that
size. The result is a size distribution in pixels, comparable across datasets
without any assumption about what a leaf looks like.
"""
import numpy as np
import cv2


def granulometry(gray, radii=range(1, 41, 2)):
    """Pattern spectrum: fraction of total intensity removed at each disc radius."""
    g = gray.astype(np.float32)
    total = g.sum() + 1e-9
    prev = g
    spec = []
    for r in radii:
        se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
        cur = cv2.morphologyEx(g, cv2.MORPH_OPEN, se)
        spec.append(float((prev.sum() - cur.sum()) / total))
        prev = cur
    return np.array(spec)


def mean_structure_size(spec, radii):
    """Intensity-weighted mean radius of the pattern spectrum, in pixels."""
    r = np.asarray(list(radii), float)
    w = np.maximum(spec, 0)
    return float((r * w).sum() / max(w.sum(), 1e-9))


def dataset_spectrum(ds, n=60, radii=range(1, 41, 2), invert=False):
    """Average pattern spectrum over a dataset.

    `invert` measures DARK structures (inter-leaf gaps and shadow) instead of
    bright ones, which is the complementary view of the same canopy.
    """
    acc = None
    used = 0
    for s in ds.stems[:n]:
        g = cv2.cvtColor(ds.read_rgb(s), cv2.COLOR_RGB2GRAY)
        if invert:
            g = 255 - g
        sp = granulometry(g, radii)
        acc = sp if acc is None else acc + sp
        used += 1
    return acc / max(used, 1)
