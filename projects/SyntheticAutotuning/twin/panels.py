"""Figures for the eye: per-plant real/synthetic panels and whole-frame overlays."""
import os

import cv2
import numpy as np

from . import raster as TR
from . import real as R


def plant_panels(target, sites, ov, workdir, path, pad=40, tile=220, max_plants=16):
    """One column per fitted plant: real crop, real mask, synthetic silhouette, overlap.

    Real crops are cut from the undistorted frame around the plant's bounding box; the
    synthetic silhouette is the fitted plant rasterized alone at its site (cropped maps), placed
    back into frame coordinates at the raster scale and resampled to the crop.
    """
    from . import fit as F
    sc = F.px_scale(ov)
    labels = getattr(target, "plant_labels", target.labels)
    cols = []
    for k, s in enumerate(sites[:max_plants]):
        lab = s["label"]
        ys, xs = np.nonzero(labels == lab)
        if len(xs) == 0:
            continue
        x0, x1 = max(0, xs.min() - pad), min(R.WIDTH, xs.max() + pad)
        y0, y1 = max(0, ys.min() - pad), min(R.HEIGHT, ys.max() + pad)
        crop = target.rgb[y0:y1, x0:x1]
        real_mask = (labels[y0:y1, x0:x1] == lab)
        m = F.single_plant(ov, s["age"], s["seed"], s["x"], s["y"], s["yaw_deg"], workdir=workdir, base=f"panel_{k}")
        syn_full = F.place(m.vegetation, m.x0, m.y0, int(round(R.WIDTH * sc)), int(round(R.HEIGHT * sc)))
        syn = cv2.resize(syn_full.astype(np.uint8), (R.WIDTH, R.HEIGHT), interpolation=cv2.INTER_NEAREST)[y0:y1, x0:x1] > 0
        h, w = crop.shape[:2]
        f = tile / max(h, w)
        size = (max(1, int(w * f)), max(1, int(h * f)))
        a = cv2.resize(crop, size, interpolation=cv2.INTER_AREA)
        b = np.zeros_like(a); b[cv2.resize(real_mask.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST) > 0] = (60, 200, 60)
        c = np.zeros_like(a); c[cv2.resize(syn.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST) > 0] = (220, 60, 220)
        d = a.copy()
        rm = cv2.resize(real_mask.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST) > 0
        sm = cv2.resize(syn.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST) > 0
        d[rm & ~sm] = (0.5 * d[rm & ~sm] + [0, 100, 0]).astype(np.uint8)
        d[sm & ~rm] = (0.5 * d[sm & ~rm] + [110, 0, 110]).astype(np.uint8)
        d[sm & rm] = (0.5 * d[sm & rm] + [110, 110, 0]).astype(np.uint8)
        col = np.zeros((4 * tile + 30, tile, 3), np.uint8)
        for i, im in enumerate((a, b, c, d)):
            col[i * tile : i * tile + im.shape[0], : im.shape[1]] = im
        cv2.putText(col, f"{k}: age {s['age']:.0f} IoU {s.get('iou', 0):.2f}", (4, 4 * tile + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
        cols.append(col)
    sheet = np.concatenate(cols, axis=1) if cols else np.zeros((10, 10, 3), np.uint8)
    cv2.imwrite(path, cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 90])
    return sheet


def side_by_side(real_rgb, syn_rgb, path, width=1296):
    """Real frame beside a developed render, same size."""
    h = int(real_rgb.shape[0] * width / real_rgb.shape[1])
    a = cv2.resize(real_rgb, (width, h), interpolation=cv2.INTER_AREA)
    b = cv2.resize(syn_rgb, (width, h), interpolation=cv2.INTER_AREA)
    cv2.imwrite(path, cv2.cvtColor(np.concatenate([a, b], axis=1), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 88])


def three_pane(real_rgb, syn_rgb, syn_mask, path, width=1400, label=None):
    """Real frame | developed synthetic | real frame with the synthetic plant masks overlaid.

    `syn_mask` is the rendered scene's vegetation (site label map > 0 or the raster's vegetation),
    in the real frame's pixel grid. The overlay fills the mask with translucent magenta and draws
    its outline, so both the coverage and the outline can be judged against the photo.
    """
    h = int(real_rgb.shape[0] * (width / 3) / real_rgb.shape[1])
    w = width // 3
    a = cv2.resize(real_rgb, (w, h), interpolation=cv2.INTER_AREA)
    b = cv2.resize(syn_rgb, (w, h), interpolation=cv2.INTER_AREA)
    m = cv2.resize(syn_mask.astype(np.uint8), (w, h), interpolation=cv2.INTER_AREA) > 0.5
    c = a.copy()
    c[m] = (0.55 * c[m] + 0.45 * np.array([230, 60, 230])).astype(np.uint8)
    edges = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)) > 0
    c[edges] = (255, 0, 255)
    sheet = np.concatenate([a, b, c], axis=1)
    if label:
        cv2.putText(sheet, label, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3)
        cv2.putText(sheet, label, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
    cv2.imwrite(path, cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 82])
    return sheet


def four_pane(real_rgb, base_rgb, syn_rgb, syn_mask, path, width=2000, labels=("real", "naive baseline", "tuned twin", "twin masks on real")):
    """Real frame | naive baseline render | tuned twin render | real frame with the twin's plant masks."""
    w = width // 4
    h = int(real_rgb.shape[0] * w / real_rgb.shape[1])
    panes = [cv2.resize(im, (w, h), interpolation=cv2.INTER_AREA) for im in (real_rgb, base_rgb, syn_rgb)]
    m = cv2.resize(syn_mask.astype(np.uint8), (w, h), interpolation=cv2.INTER_AREA) > 0.5
    c = panes[0].copy()
    c[m] = (0.55 * c[m] + 0.45 * np.array([230, 60, 230])).astype(np.uint8)
    edges = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)) > 0
    c[edges] = (255, 0, 255)
    panes.append(c)
    for im, lab in zip(panes, labels):
        cv2.putText(im, lab, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3)
        cv2.putText(im, lab, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    sheet = np.concatenate(panes, axis=1)
    cv2.imwrite(path, cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 82])
    return sheet
