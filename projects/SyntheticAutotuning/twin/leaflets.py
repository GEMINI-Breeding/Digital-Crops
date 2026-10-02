"""Leaf-level observables: visible leaflet size and shape, and how much of a plant is thin structure.

Silhouettes identify how compact a plant is and little else (TWIN_DESIGN.md 4.5): a small flat leaflet and a larger folded or
steeply pitched one cover the same pixels, and long petioles trade against leaf size in a footprint. These measures separate
them, and are taken the same way on both sides:

  leaflet segments   one mask per visible leaflet, measured by its largest connected piece: area, fitted-ellipse major and
                     minor axes, and solidity. Real leaflets come from SAM on the photo; synthetic ones exactly from the
                     rasterizer's per-leaflet object map. The same size and solidity filters apply to both, so a leaflet
                     occluded to a sliver or two leaflets merged into one blob are dropped on either side.
  thin fraction      the share of a plant's vegetation pixels that a morphological opening removes: petioles, stems and
                     leaflet edges seen on end. Taken on the vegetation mask at the rasterizer's scale on both sides.

All lengths are in full-resolution pixels of the undistorted frame.
"""
import cv2
import numpy as np

MIN_AREA_PX = 150          # full resolution; below this a segment is a fragment, not a leaflet
MIN_SOLIDITY = 0.80        # area / convex hull area: leaflets are convex, merged leaflets and canopy pieces are not
MAX_PLANT_FRACTION = 0.5   # a segment larger than this share of its plant is the plant, not a leaflet
MIN_VEG_FRACTION = 0.75    # a SAM mask must lie mostly on the plant's vegetation
THIN_OPEN_PX = 5           # opening diameter at raster scale 0.5 (about 7 mm at the canopy): removes petioles, keeps leaflets
LEAFLETS_PER_LEAF = 3      # cowpea's trifoliate leaf; set_species() changes it with the two species-dependent filters


def set_species(name):
    """Leaflet filters and leaflets per leaf of a species (twin.species); cowpea's are the values above."""
    global MIN_SOLIDITY, MAX_PLANT_FRACTION, LEAFLETS_PER_LEAF
    from . import species as S
    sp = S.get(name)
    MIN_SOLIDITY, MAX_PLANT_FRACTION, LEAFLETS_PER_LEAF = sp["leaflet_min_solidity"], sp["leaflet_max_plant_fraction"], sp["leaflets_per_leaf"]


def segment_stats(mask, scale=1.0):
    """Stats of a boolean mask's largest connected piece, or None if it fails the filters. `scale` converts the mask's pixels
    to full-resolution pixels (2 for a raster at scale 0.5)."""
    m8 = mask.astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m8, connectivity=8)
    if n <= 1:
        return None
    k = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    piece = (lab == k).astype(np.uint8)
    area = float(st[k, cv2.CC_STAT_AREA]) * scale * scale
    if area < MIN_AREA_PX:
        return None
    cnt, _ = cv2.findContours(piece, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = max(cnt, key=cv2.contourArea)
    hull_area = cv2.contourArea(cv2.convexHull(c))
    if hull_area <= 0:
        return None
    solidity = float(st[k, cv2.CC_STAT_AREA]) / hull_area
    if solidity < MIN_SOLIDITY or len(c) < 5:
        return None
    (_, _), (ax1, ax2), _ = cv2.fitEllipse(c)
    major, minor = max(ax1, ax2) * scale, min(ax1, ax2) * scale
    return dict(area=area, major=major, minor=minor, aspect=minor / max(major, 1e-6), solidity=solidity)


def synthetic_leaflets(obj, cls, site=None, site_id=None, scale=2.0, plant_area_px=None):
    """Visible leaflet segments from rasterizer maps (optionally restricted to one site). Leaf class is 1."""
    leaf = cls == 1
    if site is not None:
        leaf &= site == site_id
    ids = np.unique(obj[leaf & (obj > 0)])
    if plant_area_px is None:
        plant_area_px = float(leaf.sum()) * scale * scale
    out = []
    for i in ids:
        s = segment_stats(leaf & (obj == i), scale)
        if s is not None and s["area"] <= MAX_PLANT_FRACTION * plant_area_px:
            out.append(s)
    return out


def thin_fraction(veg):
    """Share of vegetation pixels removed by an opening of THIN_OPEN_PX: thin structure (petioles, stems, edge-on leaflets)."""
    v = veg.astype(np.uint8)
    total = int(v.sum())
    if total == 0:
        return 0.0
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (THIN_OPEN_PX, THIN_OPEN_PX))
    opened = cv2.morphologyEx(v, cv2.MORPH_OPEN, k)
    return float(1.0 - opened.sum() / total)


def sam_leaflets(model, rgb, plant_mask, margin=24, device=0):
    """Leaflet segments of one plant in a photo (or a render) by SAM in segment-everything mode on the plant's crop.

    Overlapping masks (SAM returns a leaflet and its halves, or two leaflets and their union) are resolved largest first:
    a mask is kept only if at most 30% of it is already claimed. Merged blobs are mostly rejected by the solidity filter
    before that, so this prefers whole leaflets over their parts."""
    ys, xs = np.nonzero(plant_mask)
    if len(xs) == 0:
        return []
    H, W = plant_mask.shape
    x0, x1 = max(0, xs.min() - margin), min(W, xs.max() + margin + 1)
    y0, y1 = max(0, ys.min() - margin), min(H, ys.max() + margin + 1)
    crop = np.ascontiguousarray(rgb[y0:y1, x0:x1, ::-1])  # ultralytics takes BGR arrays
    pm = plant_mask[y0:y1, x0:x1]
    plant_area = float(pm.sum())
    res = model(crop, verbose=False, device=device)
    if not res or res[0].masks is None:
        return []
    h, w = pm.shape
    masks = []
    for m in res[0].masks.data.cpu().numpy():
        mk = m > 0.5
        if mk.shape != pm.shape:
            mk = cv2.resize(mk.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST) > 0
        a = int(mk.sum())
        if a == 0 or pm[mk].mean() < MIN_VEG_FRACTION or a > MAX_PLANT_FRACTION * plant_area:
            continue
        yy, xx = np.nonzero(mk)
        if yy.min() == 0 or xx.min() == 0 or yy.max() == h - 1 or xx.max() == w - 1:
            continue
        masks.append(mk)
    masks.sort(key=lambda m: -int(m.sum()))
    claimed = np.zeros(pm.shape, bool)
    out = []
    for mk in masks:
        a = int(mk.sum())
        if (claimed & mk).sum() > 0.3 * a:
            continue
        s = segment_stats(mk, 1.0)
        if s is None:
            continue
        claimed |= mk
        out.append(s)
    return out


def summarise(segments):
    """Per-plant summary of leaflet segments."""
    if not segments:
        return dict(n=0, major=0.0, minor=0.0, aspect=0.0, sqrt_area=0.0)
    a = {k: np.array([s[k] for s in segments]) for k in ("major", "minor", "aspect", "area")}
    return dict(n=len(segments), major=float(np.median(a["major"])), minor=float(np.median(a["minor"])),
                aspect=float(np.median(a["aspect"])), sqrt_area=float(np.median(np.sqrt(a["area"]))))
