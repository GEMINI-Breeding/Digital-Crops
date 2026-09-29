"""orient_jpeg shared by the white balance galleries."""
import cv2
import numpy as np


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
