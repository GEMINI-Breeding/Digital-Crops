"""Cut 640x640 training tiles from full-resolution renders.

Why tiling is part of closing the canopy-cover gap, not just a packaging step:

The real training tiles average 0.975 vegetation cover, but the real FULL FRAMES
they came from average 0.838, and the best 640x640 crop obtainable from one of
those frames is 0.979 -- only 1.7 % of crops reach the tile median. The real
tiles were therefore selected toward the densest parts of the frame. Chasing
0.975 by making the synthetic field denser would over-densify it relative to the
actual field AND push canopy height past the 0.54 m that camera geometry pins.
The honest fix is to raise field density to the real FRAME-level cover and then
reproduce the tile SELECTION.

Tiles are cut at native resolution so the ground sampling distance measured from
the rig (0.440 mm/px) is preserved exactly -- no resampling.
"""
import os
import numpy as np
import cv2

TILE = 640

# The smallest object the real annotator marked, as the 5th percentile of real box size in tile
# pixels (23.4 px, about 21 mm on the ground). Nothing in the 1,991 real boxes is smaller than a
# corolla; the renderer by contrast annotates every flower object in the scene, including 14 mm
# green buds that outnumber the open flowers 3:1. Those are targets the detector would be trained
# to find and never rewarded for, so they are dropped at the annotator's own visibility floor
# rather than at an invented threshold.
REAL_MIN_BOX_PX = 23.4

# Measured on the real training set: fraction of boxes touching the tile border.
# The real pipeline KEEPS truncated boxes (7.4 % of them), it does not drop them.
REAL_EDGE_TRUNC_RATE = 0.0743

# Real tile vegetation-cover distribution (excess-green, fixed 0.05 threshold).
REAL_COVER_Q = {5: 0.807, 25: 0.940, 50: 0.975, 75: 0.989, 95: 0.996}


def _exg(rgb):
    f = rgb.astype(np.float32) / 255.0
    s = f.sum(2) + 1e-6
    return 2 * f[..., 1] / s - f[..., 0] / s - f[..., 2] / s


def load_boxes(path):
    """YOLO labels normalized to the FULL frame -> (N,5) [cls,cx,cy,w,h]."""
    if not os.path.exists(path):
        return np.zeros((0, 5))
    rows = [[float(x) for x in ln.split()] for ln in open(path) if len(ln.split()) == 5]
    return np.array(rows).reshape(-1, 5)


def candidate_tiles(W, H, tile=TILE, stride=None):
    stride = stride or tile // 4
    xs = list(range(0, max(W - tile, 0) + 1, stride))
    ys = list(range(0, max(H - tile, 0) + 1, stride))
    if xs and xs[-1] != W - tile:
        xs.append(W - tile)
    if ys and ys[-1] != H - tile:
        ys.append(H - tile)
    return [(x, y) for y in ys for x in xs]


def tile_cover(veg, x, y, tile=TILE):
    """Vegetation fraction of one candidate tile, from a boolean vegetation mask."""
    return float(veg[y:y + tile, x:x + tile].mean())


def load_ground_mask(path):
    """Exact soil mask written by the renderer, as a boolean where True means ground.

    Tile selection is inverse-transform sampling against the real cover quantiles, so it is only as
    good as its cover measure. Excess Green was that measure, and it recovers barely a quarter of
    the soil in a synthetic frame: measured against exact masks it called a frame of 0.913 true
    canopy 0.975, and on a deliberately sparse frame of 0.30 true canopy it said 0.98. Selection was
    therefore matching a statistic that could not see the thing it was selecting on.
    """
    a = np.loadtxt(path)
    return np.isfinite(a) & (a > 0)


def load_rover_mask(path):
    """Exact rover mask written by the renderer, or None if absent.

    Preferred over any pixel heuristic: two attempts to infer hardware from the
    image failed -- a texture test rejected smooth bright soil alongside painted
    metal, and an explicit crop region still admitted structural members at tile
    edges. The renderer knows where the rover is.
    """
    if not os.path.exists(path):
        return None
    # writePrimitiveDataLabelMap emits a text grid: the primitive-data value
    # where a tagged primitive was hit, NaN elsewhere.
    a = np.loadtxt(path)
    return np.isfinite(a) & (a > 0)


def manufactured_mask(rgb, sat_max=0.14, v_min=0.35, var_max=12.0, win=9):
    """DEPRECATED pixel heuristic, kept only for reference. See load_rover_mask.

    The T4 body is in every rendered frame and shows up at the edges and in
    vertical bands. The real training tiles contain no rover hardware at all, so
    any tile that catches some is off-distribution and must be rejected.

    Hardware is separated from bright soil by TEXTURE, not brightness: painted
    metal is smooth and desaturated, soil is bright and desaturated but grainy.
    """
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    S = hsv[..., 1].astype(np.float32) / 255
    V = hsv[..., 2].astype(np.float32) / 255
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    m = cv2.blur(g, (win, win))
    var = np.maximum(cv2.blur(g * g, (win, win)) - m * m, 0)
    return (S < sat_max) & (V > v_min) & (var < var_max)


def remap_boxes(boxes, x, y, W, H, tile=TILE, min_visible=0.35, min_box_px=REAL_MIN_BOX_PX):
    """Full-frame boxes -> tile-local YOLO boxes.

    Boxes are clipped to the tile and kept if enough of their area survives.
    `min_visible` is the knob that controls the edge-truncation rate; it is tuned
    against REAL_EDGE_TRUNC_RATE rather than guessed.

    `min_box_px` drops objects smaller than the real annotator evidently marked. The renderer
    annotates every flower object it can see, including green primordia a few millimetres across;
    the real annotations contain nothing that small, so exporting them creates a class of target
    that exists only in the synthetic set. Applied after clipping, so a large object clipped to a
    sliver at the tile edge is governed by `min_visible` and not by this.
    """
    out = []
    for cls, cx, cy, bw, bh in boxes:
        ax0, ay0 = (cx - bw / 2) * W, (cy - bh / 2) * H
        ax1, ay1 = (cx + bw / 2) * W, (cy + bh / 2) * H
        ix0, iy0 = max(ax0, x), max(ay0, y)
        ix1, iy1 = min(ax1, x + tile), min(ay1, y + tile)
        if ix1 <= ix0 or iy1 <= iy0:
            continue
        area0 = (ax1 - ax0) * (ay1 - ay0)
        if area0 <= 0 or ((ix1 - ix0) * (iy1 - iy0)) / area0 < min_visible:
            continue
        if min_box_px > 0 and np.sqrt((ax1 - ax0) * (ay1 - ay0)) * TILE / tile < min_box_px:
            continue
        out.append([int(cls),
                    ((ix0 + ix1) / 2 - x) / tile, ((iy0 + iy1) / 2 - y) / tile,
                    (ix1 - ix0) / tile, (iy1 - iy0) / tile])
    return np.array(out).reshape(-1, 5)


def select_by_cover(covers, n, rng, widen=1.0):
    """Pick n tiles whose cover distribution matches the real one.

    Inverse-transform sampling: draw target covers from the real quantiles, then
    take the candidate nearest each target, without replacement. `widen` > 1
    inflates the spread about the median, which the project's asymmetric
    objective rewards -- being wider than real costs nothing, being narrower
    means real modes the detector never sees.
    """
    q = np.array(sorted(REAL_COVER_Q))
    v = np.array([REAL_COVER_Q[k] for k in q])
    med = REAL_COVER_Q[50]
    u = rng.uniform(0, 100, size=n)
    targets = np.interp(u, q, v)
    targets = np.clip(med + (targets - med) * widen, 0.0, 1.0)

    covers = np.asarray(covers)
    chosen, used = [], np.zeros(len(covers), bool)
    for t in targets:
        d = np.abs(covers - t)
        d[used] = np.inf
        k = int(np.argmin(d))
        if not np.isfinite(d[k]):
            break
        used[k] = True
        chosen.append(k)
    return chosen


def jpeg_roundtrip(rgb, quality=75):
    """Re-encode at the REAL camera's JPEG quality.

    Measured: the real tiles' luma quantization table sums to 1858, which
    libjpeg quality 75 reproduces exactly; the synthetic set was at 369 (~q95).
    Compression artefacts are a shortcut feature a detector will happily learn.
    """
    ok, buf = cv2.imencode('.jpg', cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
                           [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def add_sensor_noise(rgb, sigma, rng, correlation=2):
    """Spatially-correlated sensor noise.

    White Gaussian noise does not survive JPEG: at quality 75 the measured noise
    level saturated at ~1.7 no matter how much was injected, against a real 2.21.
    Real camera noise is correlated across neighbouring pixels because it is
    demosaiced from a Bayer mosaic, and that lower-frequency grain passes through
    quantization largely intact. Generating the noise at reduced resolution and
    upsampling reproduces that correlation.
    """
    h, w = rgb.shape[:2]
    if correlation <= 1:
        n = rng.normal(0, sigma, rgb.shape)
    else:
        sh, sw = max(h // correlation, 1), max(w // correlation, 1)
        small = rng.normal(0, sigma, (sh, sw, 3))
        n = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
        # upsampling averages away variance; renormalize to the requested sigma
        cur = n.std()
        if cur > 1e-6:
            n *= sigma / cur
    return np.clip(rgb.astype(np.float32) + n, 0, 255).astype(np.uint8)


def tile_frame(image_path, label_path, out_dir, n_tiles=6, seed=0,
               jpeg_quality=75, noise_sigma=0.0, widen=1.0, min_visible=0.35,
               stride=None, noise_correlation=2,
               crop_x=(0.05, 0.87), crop_y=(0.14, 0.86), native=2 * TILE,
               rover_mask_path=None, min_box_px=REAL_MIN_BOX_PX, ground_mask_path=None):
    rng = np.random.default_rng(seed)
    bgr = cv2.imread(image_path)
    if bgr is None:
        raise IOError(f'cannot read {image_path}')
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    H, W = rgb.shape[:2]
    boxes = load_boxes(label_path)
    # Vegetation for tile selection: the exact ground mask when the renderer wrote one, otherwise
    # Excess Green. The two are not interchangeable and the fallback is only for real imagery,
    # which has no ground truth.
    if ground_mask_path is not None and os.path.exists(ground_mask_path):
        veg = ~load_ground_mask(ground_mask_path)
    else:
        veg = _exg(rgb) > 0.05

    # Restrict sampling to the part of the frame that contains no rover hardware.
    #
    # The T4 body appears at both side edges and in bands near the top and bottom
    # of every frame. The real training tiles contain no hardware, so tiles that
    # catch some are off-distribution. A texture-based detector was tried first
    # and failed: the synthetic soil is a nearly flat tile, so it is as smooth and
    # desaturated as painted metal and got rejected alongside it. The rover does
    # not move between renders, so an explicit region is both simpler and safer.
    # Cut `native` pixels and resample to TILE.
    #
    # These were previously cut at native resolution on the assumption that the
    # real tiles were native crops. A physical check says otherwise: at native
    # GSD (0.440 mm/px) the real median flower box of 33 px would be a 14.5 mm
    # flower, which no cowpea has. At half that resolution it is 29 mm, which is
    # right. The real tiles are therefore ~2x downsampled, and cutting synthetic
    # tiles natively made every structure in them twice the pixel size.
    nat = int(native)
    rover = load_rover_mask(rover_mask_path) if rover_mask_path else None
    x0, x1 = int(crop_x[0] * W), int(crop_x[1] * W) - nat
    y0, y1 = int(crop_y[0] * H), int(crop_y[1] * H) - nat
    cands = [(x, y) for (x, y) in candidate_tiles(W, H, nat, stride)
             if x0 <= x <= max(x1, x0) and y0 <= y <= max(y1, y0)]
    if len(cands) < n_tiles:
        cands = candidate_tiles(W, H, nat, stride)
    if rover is not None and rover.shape == veg.shape:
        clean = [(x, y) for (x, y) in cands if not rover[y:y + nat, x:x + nat].any()]
        if len(clean) >= max(n_tiles // 2, 4):
            cands = clean
    covers = [tile_cover(veg, x, y, nat) for x, y in cands]
    picks = select_by_cover(covers, n_tiles, rng, widen)

    os.makedirs(os.path.join(out_dir, 'images'), exist_ok=True)
    os.makedirs(os.path.join(out_dir, 'labels'), exist_ok=True)
    stem = os.path.splitext(os.path.basename(image_path))[0]
    written = []
    for i, k in enumerate(picks):
        x, y = cands[k]
        crop = rgb[y:y + nat, x:x + nat].copy()
        if nat != TILE:
            crop = cv2.resize(crop, (TILE, TILE), interpolation=cv2.INTER_AREA)
        if noise_sigma > 0:
            crop = add_sensor_noise(crop, noise_sigma, rng, correlation=noise_correlation)
        # Encode ONCE. An earlier version ran jpeg_roundtrip() and then wrote the
        # file, compressing twice; the second pass scrubbed the added sensor
        # noise (measured noise_sigma stuck at ~1.3 no matter how much was
        # injected) and is not what the real single-encode pipeline did.
        name = f'{stem}_T{i:02d}'
        cv2.imwrite(os.path.join(out_dir, 'images', name + '.jpeg'),
                    cv2.cvtColor(crop, cv2.COLOR_RGB2BGR),
                    [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)])
        tb = remap_boxes(boxes, x, y, W, H, nat, min_visible, min_box_px)
        with open(os.path.join(out_dir, 'labels', name + '.txt'), 'w') as f:
            for r in tb:
                f.write(f'{int(r[0])} {r[1]:.6f} {r[2]:.6f} {r[3]:.6f} {r[4]:.6f}\n')
        written.append((name, covers[k], len(tb)))
    return written
