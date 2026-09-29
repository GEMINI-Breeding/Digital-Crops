"""Read the annotations written by the rasterized geometry pass (``SyntheticAutotuning geom``).

The geometry pass renders the full 2592x2048 sensor frame, while the real dataset -- and the
tiled synthetic set built to match it -- is 640x640 tiles cut at 1280 native pixels and
downsampled 2x. Object sizes are therefore reported here in *tile pixels*, so they can be compared
against the real label statistics without a further conversion at every call site.
"""

from __future__ import annotations

import os

import numpy as np

#: Native frame pixels per tile pixel. The real tiles are ~2x downsampled from the sensor.
TILE_DOWNSAMPLE = 2.0


def read_classes(view_dir):
    """Return the class-index -> name mapping written beside the annotations."""
    path = os.path.join(view_dir, "classes.txt")
    if not os.path.exists(path):
        raise FileNotFoundError(f"no classes.txt in {view_dir}")
    with open(path) as handle:
        return {i: line.strip() for i, line in enumerate(handle) if line.strip()}


def read_boxes(geom_dir, view=0, frame_size=(2592, 2048)):
    """Read one view's YOLO boxes as a structured array.

    Fields: ``cls`` (index), ``name`` (class name), ``cx``/``cy`` (normalized centre), ``w``/``h``
    (size in tile pixels), ``size`` (sqrt of the box area, tile pixels), ``aspect`` (w/h).
    """
    view_dir = os.path.join(geom_dir, f"view{view:05d}")
    names = read_classes(view_dir)
    path = os.path.join(view_dir, "RGB_rendering.txt")
    if not os.path.exists(path):
        raise FileNotFoundError(f"no annotations in {view_dir}; was object detection enabled?")

    W, H = frame_size
    records = []
    with open(path) as handle:
        for line in handle:
            parts = line.split()
            if len(parts) < 5:
                continue
            cls = int(float(parts[0]))
            cx, cy, w, h = (float(v) for v in parts[1:5])
            if w <= 0 or h <= 0:
                continue
            w_px = w * W / TILE_DOWNSAMPLE
            h_px = h * H / TILE_DOWNSAMPLE
            records.append((cls, names.get(cls, str(cls)), cx, cy, w_px, h_px, np.sqrt(w_px * h_px), w_px / h_px))

    if not records:
        return np.empty(0, dtype=[("cls", "i4"), ("name", "U32"), ("cx", "f4"), ("cy", "f4"), ("w", "f4"), ("h", "f4"), ("size", "f4"), ("aspect", "f4")])
    return np.array(records, dtype=[("cls", "i4"), ("name", "U32"), ("cx", "f4"), ("cy", "f4"), ("w", "f4"), ("h", "f4"), ("size", "f4"), ("aspect", "f4")])


def summarize(boxes, classes=None):
    """Per-class median size and aspect, plus the count. Sizes are in tile pixels."""
    out = {}
    names = classes if classes is not None else sorted(set(boxes["name"].tolist()))
    for name in names:
        sel = boxes[boxes["name"] == name]
        if len(sel) == 0:
            out[name] = dict(n=0)
            continue
        out[name] = dict(
            n=int(len(sel)),
            size_p50=float(np.median(sel["size"])),
            size_p95=float(np.percentile(sel["size"], 95)),
            aspect_p50=float(np.median(sel["aspect"])),
            frac_narrow=float(np.mean(sel["aspect"] < 0.6)),
        )
    return out


def nn_spacing(boxes, frame_size=(2592, 2048)):
    """Nearest-neighbour distance between object centres, in tile pixels.

    Measured across the whole frame, so it is not directly comparable to a spacing measured inside
    640 px tiles -- a tile truncates neighbours that fall outside it, which biases that statistic
    upward. Use this to compare one synthetic setting against another, not against the real value.
    """
    if len(boxes) < 2:
        return float("nan")
    W, H = frame_size
    pts = np.stack([boxes["cx"] * W / TILE_DOWNSAMPLE, boxes["cy"] * H / TILE_DOWNSAMPLE], axis=1)
    d = np.linalg.norm(pts[:, None, :] - pts[None, :, :], axis=-1)
    np.fill_diagonal(d, np.inf)
    return float(np.median(d.min(axis=1)))


#: Radius grid for the pattern spectrum, in half-resolution pixels; reported radii are doubled.
#: Matches scripts/granulo_v17.py exactly so the real and synthetic spectra are the same measurement.
HALF_RADII = list(range(1, 61, 3))
REPORTED_RADII = [2 * r for r in HALF_RADII]

#: Rasterized-to-ray-traced calibration for the mean structure radius, from
#: scripts/validate_granulometry.py: five leaf scales x two seeds, Spearman +0.90 (p 0.037),
#: RMS residual 0.68 px. The rasterized image is Phong-shaded from one fixed light, so its spectrum
#: sits ~10 px below the ray-traced one and compresses it by about 20%; the ordering survives, which
#: is what an optimiser needs. Apply this before comparing a rasterized value to a real target.
GRANULO_CALIBRATION = (0.7935, 16.385)


def calibrated_mean_radius(rasterized_mean_r):
    """Rasterized mean structure radius mapped onto the ray-traced (and hence real) scale."""
    slope, intercept = GRANULO_CALIBRATION
    return slope * float(rasterized_mean_r) + intercept


def granulometry_from_render(geom_dir, view=0, native_per_tile_px=2.0):
    """Pattern spectrum of the geom pass's RGB rendering, on the real set's scale and radius grid.

    The real spectrum is computed on 640 px tiles, halved for speed with the radii doubled back.
    The geom pass renders a full 2592x2048 sensor frame at native resolution, so two rescalings are
    needed to land on the same axis: native -> tile pixels (the real tiles are ~2x downsampled from
    the sensor, `native_per_tile_px`), then tile -> half for the same speed trick. The frame is then
    cut into 320 px windows -- 640 tile px, one real tile -- and their spectra averaged, because a
    whole frame carries inter-plant structure that a tile does not and the two would not otherwise
    be comparable.

    Returns (peak_radius_px, mean_radius_px, spectrum). Raises if the rendering is absent: the geom
    pass writes it only under `geom.write_rgb 1`, and a missing file means the run was configured
    without it rather than that the spectrum is zero.

    Only the mean radius is usable as an objective. Across a leaf-scale sweep spanning 0.08-0.23 m
    the rasterized peak radius never moved off 8 px while the ray-traced peak jumped 17/11/11/8/17,
    so the peak carries no signal on this side and is not monotonic on the other. It is returned for
    description, not for scoring.
    """
    import cv2
    from .geometry import granulometry

    path = os.path.join(geom_dir, f"view{view:05d}", "RGB_rendering.jpeg")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"no RGB rendering at {path}; the geom pass writes one only with 'geom.write_rgb 1'")
    bgr = cv2.imread(path)
    if bgr is None:
        raise IOError(f"could not decode {path}")
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    shrink = native_per_tile_px * 2.0
    small = cv2.resize(gray, (int(gray.shape[1] / shrink), int(gray.shape[0] / shrink)),
                       interpolation=cv2.INTER_AREA)

    window = 320                                   # 640 tile px at half resolution: one real tile
    spectra = []
    for y in range(0, small.shape[0] - window + 1, window):
        for x in range(0, small.shape[1] - window + 1, window):
            spectra.append(granulometry(small[y:y + window, x:x + window], HALF_RADII))
    if not spectra:
        spectra = [granulometry(small, HALF_RADII)]
    spec = np.mean(spectra, axis=0)
    radii = np.asarray(REPORTED_RADII, float)
    total = spec.sum()
    if total <= 0:
        raise ValueError(f"degenerate pattern spectrum from {path}: no structure at any radius")
    return float(radii[int(np.argmax(spec))]), float((radii * spec).sum() / total), spec
