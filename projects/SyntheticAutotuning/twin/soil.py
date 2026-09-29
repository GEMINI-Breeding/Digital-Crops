"""The real frame's soil as the ground albedo of the twin.

For a twin of one frame the soil is a directly observed, static background, so instead of a
library spectrum on a flat tile the ground gets a per-patch reflectance taken from the photo:
soil pixels are run backwards through the development chain (display sRGB -> linear -> inverse
colour matrix -> inverse white balance), scaled so the median soil reflectance equals the
calibrated scalar, and written as a map over the bed that the renderer samples per ground
sub-patch (`scene.soil_albedo_map` in main.cpp, per-band `reflectivity_red/green/blue`).
Pixels hidden by plants or the rover, and bed positions outside the frame, are filled by
`texture_fill()`: the large-scale brightness is carried in from the visible soil, and the
high-frequency texture is borrowed from the best-observed patch and mirror-tiled over the hole.
A diffusion inpaint (`texture_fill=False`) was used before and left wide smears wherever the
hidden region was more than a few centimetres across, which a tilted view shows plainly. Shadows in the photo are not removed, so the twin's soil carries the real
frame's shading on top of the render's own; that is a known approximation.
"""
import os
import struct

import cv2
import numpy as np

from . import appearance as A
from . import real as R

#: Bed extent of the ground tile in main.cpp: 3 x 3.048 m centred on the origin.
TILE_X, TILE_Y = 3.0, 3.048


def srgb_to_linear(x):
    x = x.astype(np.float32) / 255.0
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def texture_fill(raw, soil, donor_px=384, trend_sigma=80.0):
    """Fill everything outside `soil` with the visible soil's brightness trend plus real soil texture.

    The trend is a normalized-convolution blur of the visible pixels, which extrapolates smoothly into the holes. The texture is
    the residual of the best-observed square of the image, mirror-tiled; mirroring means the tile joins itself without a seam.
    Visible pixels are returned unchanged."""
    m = soil.astype(np.float32)
    k = int(max(3, round(trend_sigma * 3)) // 2 * 2 + 1)
    blur = lambda img: cv2.GaussianBlur(img, (k, k), trend_sigma, borderType=cv2.BORDER_REPLICATE)
    weight = np.maximum(blur(m), 1e-6)
    trend = np.stack([blur(raw[..., c] * m) / weight for c in range(3)], -1)
    # Far from any visible soil -- behind the rails at the frame edges -- the blur carries almost no weight and its quotient is
    # meaningless, so fade the trend to the median soil colour there rather than let it run to zero.
    confidence = np.clip(weight / 0.02, 0.0, 1.0)[..., None]
    median_soil = np.median(raw[soil], axis=0).astype(np.float32)
    trend = confidence * trend + (1.0 - confidence) * median_soil
    # the donor: the densest square of visible soil
    integral = cv2.integral(m)
    best, best_xy = -1.0, (0, 0)
    for y in range(0, soil.shape[0] - donor_px, 64):
        for x in range(0, soil.shape[1] - donor_px, 64):
            v = integral[y + donor_px, x + donor_px] - integral[y, x + donor_px] - integral[y + donor_px, x] + integral[y, x]
            if v > best:
                best, best_xy = v, (x, y)
    x0, y0 = best_xy
    donor = (raw - trend)[y0 : y0 + donor_px, x0 : x0 + donor_px].copy()
    donor_mask = soil[y0 : y0 + donor_px, x0 : x0 + donor_px]
    if not donor_mask.all():  # the densest square may still hold a few leaf pixels
        for c in range(3):
            scale = 4 * float(np.std(donor[..., c]) + 1e-6)
            ch = np.clip(donor[..., c] / scale * 0.5 + 0.5, 0, 1)
            ch = cv2.inpaint((ch * 255).astype(np.uint8), (~donor_mask).astype(np.uint8), 5, cv2.INPAINT_NS)
            donor[..., c] = (ch.astype(np.float32) / 255.0 - 0.5) * scale
    donor -= donor.mean(axis=(0, 1), keepdims=True)
    # mirror-tile the donor over the frame
    h, w = raw.shape[:2]
    ty = np.arange(h) % (2 * donor_px)
    tx = np.arange(w) % (2 * donor_px)
    ty = np.where(ty < donor_px, ty, 2 * donor_px - 1 - ty)
    tx = np.where(tx < donor_px, tx, 2 * donor_px - 1 - tx)
    tiled = donor[np.ix_(ty, tx)]
    filled = np.where(soil[..., None], raw, np.maximum(trend + tiled, 0.0))
    return filled.astype(np.float32), dict(donor_xy=[int(x0), int(y0)], donor_px=int(donor_px), donor_visible=float(donor_mask.mean()))


def albedo_map(target, camera_height_m, ccm, wb=(1.563, 1.0, 1.596), median_reflectance=0.04, res=512, inpaint_radius=7, texture_fill_holes=True):
    """Per-band soil reflectance over the bed, from the real frame. Returns (map[res,res,3], meta)."""
    rgb = target.rgb
    # Grow the vegetation mask before cutting the hole: the pixels just outside a leaf are mixed
    # leaf-and-soil colour, and inpainting from them smears dark green into the footprint.
    veg_grown = cv2.dilate(target.veg.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (41, 41))) > 0
    soil = (~veg_grown) & target.valid
    lin = srgb_to_linear(rgb)
    # undo the colour matrix and the white balance (the tone curve's knee is above the soil's range)
    Minv = np.linalg.inv(np.asarray(ccm, dtype=np.float64))
    flat = lin.reshape(-1, 3) @ Minv.T
    flat /= np.asarray(wb, dtype=np.float64)[None, :]
    raw = np.clip(flat, 0, None).reshape(rgb.shape).astype(np.float32)
    # scale: the median soil pixel gets the calibrated reflectance (library soil x fitted scale)
    lum = 0.2126 * raw[..., 0] + 0.7152 * raw[..., 1] + 0.0722 * raw[..., 2]
    med = float(np.median(lum[soil]))
    raw *= median_reflectance / max(med, 1e-9)
    # fill the hidden pixels: real soil texture over the visible soil's brightness trend
    if texture_fill_holes:
        filled, fill_meta = texture_fill(raw, soil)
    else:
        fill_meta = dict(inpaint_radius=inpaint_radius)
        filled = raw.copy()
        hole = (~soil).astype(np.uint8)
        for c in range(3):
            ch = np.clip(raw[..., c] / (4 * median_reflectance), 0, 1)
            ch8 = (ch * 255).astype(np.uint8)
            ch8 = cv2.inpaint(ch8, hole, inpaint_radius, cv2.INPAINT_NS)
            filled[..., c] = ch8.astype(np.float32) / 255.0 * (4 * median_reflectance)
    # resample onto the bed grid through the pinhole: bed (x, y) -> pixel
    xs = (np.arange(res) + 0.5) / res * TILE_X - TILE_X / 2
    ys = (np.arange(res) + 0.5) / res * TILE_Y - TILE_Y / 2
    X, Y = np.meshgrid(xs, ys)
    px = R.WIDTH / 2.0 + R.FX * X / camera_height_m
    py = R.HEIGHT / 2.0 - R.FX * Y / camera_height_m
    inside = (px >= 0) & (px < R.WIDTH - 1) & (py >= 0) & (py < R.HEIGHT - 1)
    out = np.empty((res, res, 3), np.float32)
    fill = np.median(filled[soil], axis=0)
    for c in range(3):
        samp = cv2.remap(filled[..., c], px.astype(np.float32), py.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=float(fill[c]))
        samp[~inside] = fill[c]
        out[..., c] = samp
    meta = dict(res=res, tile_x=TILE_X, tile_y=TILE_Y, median_reflectance=median_reflectance, camera_height_m=camera_height_m,
                soil_pixels=int(soil.sum()), fill_rgb=[float(v) for v in fill], **fill_meta)
    return out, meta


def write_map(path, amap, meta):
    """Binary map for main.cpp: int32 res_x, res_y; float32 x0, y0, dx, dy; then float32 RGB row-major (y outer)."""
    res_y, res_x = amap.shape[:2]
    with open(path, "wb") as f:
        f.write(struct.pack("<ii", res_x, res_y))
        f.write(struct.pack("<ffff", -meta["tile_x"] / 2, -meta["tile_y"] / 2, meta["tile_x"] / res_x, meta["tile_y"] / res_y))
        f.write(amap.astype("<f4").tobytes())
    return path


def preview(amap, path, gain=6.0):
    im = np.clip(amap * gain, 0, 1) ** (1 / 2.2)
    cv2.imwrite(path, cv2.cvtColor((im * 255).astype(np.uint8), cv2.COLOR_RGB2BGR))
