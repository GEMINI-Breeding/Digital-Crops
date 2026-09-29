"""Locate colour-board patches automatically.

The boards are photographed small, tilted, and at arbitrary orientation, so
hand-clicking corners across several frames is both tedious and imprecise.
The patches themselves are the most reliable landmark: saturated or bright
squares separated by a matte black frame. Detect them as blobs, then fit the
row/column lattice by projecting centroids onto the two dominant axes.
"""
import numpy as np
import cv2


def find_patches(img_rgb, roi, n_expected, grid, min_area_frac=0.0015):
    """Detect patch centroids inside `roi` = (x0, y0, x1, y1).

    Returns (centroids_in_full_image_coords, labels_rowcol, debug_image).
    """
    x0, y0, x1, y1 = roi
    sub = img_rgb[y0:y1, x0:x1]
    hsv = cv2.cvtColor(sub, cv2.COLOR_RGB2HSV)
    S = hsv[..., 1].astype(np.float32) / 255
    V = hsv[..., 2].astype(np.float32) / 255

    # A patch is either colourful (high S) or a bright neutral (high V).
    # The black frame between patches is low in both.
    mask = ((S > 0.25) | (V > 0.45)).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))

    n, lab, stats, cent = cv2.connectedComponentsWithStats(mask, 8)
    area_min = min_area_frac * sub.shape[0] * sub.shape[1]
    keep = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= area_min]
    # squares only: reject wildly non-square components (merged patches, leaves)
    good = []
    for i in keep:
        w, h = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
        fill = stats[i, cv2.CC_STAT_AREA] / float(w * h)
        if 0.6 < w / float(h) < 1.7 and fill > 0.65:
            good.append(i)
    C = cent[good]

    rows, cols = grid
    labels = assign_lattice(C, rows, cols) if len(C) else np.zeros((0, 2), int)

    dbg = sub.copy()
    for (cx, cy), (r, c) in zip(C, labels):
        cv2.circle(dbg, (int(cx), int(cy)), 3, (255, 0, 0), -1)
        cv2.putText(dbg, f'{r}{c}', (int(cx) - 8, int(cy) - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 0), 1)
    return C + np.array([x0, y0]), labels, dbg, len(good)


def assign_lattice(C, rows, cols):
    """Assign each centroid a (row, col) index.

    The board may be rotated, so the lattice axes are recovered by PCA on the
    centroid cloud rather than assumed to be image-aligned.
    """
    X = C - C.mean(0)
    u, s, vt = np.linalg.svd(X, full_matrices=False)
    a = X @ vt[0]   # coordinate along the long axis
    b = X @ vt[1]   # along the short axis
    long_n, short_n = (rows, cols) if rows >= cols else (cols, rows)
    ra = np.argsort(np.argsort(a)) * long_n // max(len(a), 1)
    rb = np.argsort(np.argsort(b)) * short_n // max(len(b), 1)
    # quantize by rank within each axis
    def quant(v, k):
        lo, hi = v.min(), v.max()
        if hi - lo < 1e-9:
            return np.zeros(len(v), int)
        return np.clip(((v - lo) / (hi - lo) * k).astype(int), 0, k - 1)
    qa, qb = quant(a, long_n), quant(b, short_n)
    return np.stack([qa, qb], 1) if rows >= cols else np.stack([qb, qa], 1)


def sample_at(img_rgb, centroids, half=3):
    """Median RGB in a small window at each centroid."""
    out = []
    for cx, cy in centroids:
        x, y = int(round(cx)), int(round(cy))
        w = img_rgb[max(y - half, 0):y + half + 1, max(x - half, 0):x + half + 1]
        out.append(np.median(w.reshape(-1, 3), 0))
    return np.array(out, float)
