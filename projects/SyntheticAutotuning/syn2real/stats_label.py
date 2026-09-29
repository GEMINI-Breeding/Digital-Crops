"""Tier-0 statistics derived from detection labels alone (free, no image decode).

Two granularities:
  per-image  : one value per image  (e.g. object count)
  per-object : one value per box    (e.g. size, aspect)
"""
import numpy as np

PX = 640.0  # tiles are 640x640; report sizes in pixels so they are interpretable


def per_object(ds):
    """Return dict of per-object statistic arrays."""
    W, H, CX, CY = [], [], [], []
    for s in ds.stems:
        b = ds.boxes(s)
        if len(b):
            CX.append(b[:, 1]); CY.append(b[:, 2]); W.append(b[:, 3]); H.append(b[:, 4])
    w = np.concatenate(W) * PX if W else np.zeros(0)
    h = np.concatenate(H) * PX if H else np.zeros(0)
    cx = np.concatenate(CX) if CX else np.zeros(0)
    cy = np.concatenate(CY) if CY else np.zeros(0)
    return {
        'obj_width_px':      w,
        'obj_height_px':     h,
        'obj_size_px':       np.sqrt(w * h),
        'obj_log_aspect':    np.log(w / h),
        'obj_major_px':      np.maximum(w, h),
        'obj_minor_px':      np.minimum(w, h),
        'obj_abs_log_aspect': np.abs(np.log(w / h)),
        'obj_center_x':      cx,
        'obj_center_y':      cy,
    }


def per_image(ds):
    """Return dict of per-image statistic arrays."""
    count, dens, nnd, edge = [], [], [], []
    for s in ds.stems:
        b = ds.boxes(s)
        count.append(len(b))
        if len(b):
            area = (b[:, 3] * b[:, 4]).sum()
            dens.append(area)
            # fraction of boxes touching the tile border (truncation rate)
            x0, y0 = b[:, 1] - b[:, 3] / 2, b[:, 2] - b[:, 4] / 2
            x1, y1 = b[:, 1] + b[:, 3] / 2, b[:, 2] + b[:, 4] / 2
            edge.append(((x0 <= 0.002) | (y0 <= 0.002) | (x1 >= 0.998) | (y1 >= 0.998)).mean())
        else:
            dens.append(0.0); edge.append(0.0)
        if len(b) > 1:
            p = b[:, 1:3] * PX
            d = np.sqrt(((p[:, None, :] - p[None, :, :]) ** 2).sum(-1))
            np.fill_diagonal(d, np.inf)
            nnd.append(np.median(d.min(1)))
    return {
        'img_obj_count':       np.array(count, float),
        'img_obj_area_frac':   np.array(dens, float),
        'img_edge_trunc_frac': np.array(edge, float),
        'img_nn_dist_px':      np.array(nnd, float),
    }


def all_stats(ds):
    out = per_object(ds)
    out.update(per_image(ds))
    return out
