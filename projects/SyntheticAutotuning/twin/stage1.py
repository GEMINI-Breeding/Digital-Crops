"""Stage 1 as an optimiser: generator shape parameters as the outer loop.

The objective for a parameter vector theta is the mean, over a fixed set of real plants, of the
best silhouette IoU that a fixed set of seeds x yaws can reach for that plant under theta. The
seeds are the SAME for every theta (common random numbers), so two parameter vectors are
compared on paired draws and the objective is as smooth as the model allows; the inner seed
search is "best achievable", a placeholder for the leaf-level stage, not the answer.

Candidates are rasterized in batches: one process builds and draws many single plants
(`raster.each_site`), which is what makes a trial cost seconds rather than minutes.
"""
import json
import os
import time

import cv2
import numpy as np

from . import fit as F
from . import raster as TR
from . import real as R

AGES = (5, 6, 7, 8, 9, 10, 11, 12, 14, 16, 18, 20, 23, 26, 30)


# ---------------------------------------------------------------- batches ---

rasterize_many = TR.rasterize_many


# ----------------------------------------------------------- leaflet size ---

def leaflet_stats(mask, min_r=2.0, window=15):
    """Leaflet half-widths (px) and count from a plant mask alone: local maxima of the distance
    transform. No segmentation, so it works identically on the real mask and the rasterized one;
    it is the observable the silhouette IoU is blind to (leaf size and petiole length compensate
    in a footprint, so the fit chose leaflets 1.3-2x too wide and 3-7x too few)."""
    m8 = mask.astype(np.uint8)
    if m8.sum() == 0:
        return np.array([]), 0
    d = cv2.distanceTransform(m8, cv2.DIST_L2, 5)
    dil = cv2.dilate(d, np.ones((window, window), np.uint8))
    pk = (d == dil) & (d >= min_r)
    return d[pk], int(pk.sum())


# --------------------------------------------------------------- objective ---

class Stage1Objective:
    def __init__(self, target, base_ov, n_plants=8, n_seeds=6, n_yaws=8, workers=8, workdir=None, ages=AGES, table_seeds=(1, 2, 3), log=print):
        self.target = target
        self.base_ov = dict(base_ov)
        self.sc = F.px_scale(base_ov)
        plants = sorted(target.plants(min_area_px=3000, min_sep_px=120), key=lambda p: -p["area_px"])
        # every other plant by size, so the set spans the size range rather than only the largest
        self.plants = plants[: 2 * n_plants : 2] if len(plants) >= 2 * n_plants else plants[:n_plants]
        self.veg_s, self.valid_s, self.labels_s = target.downsampled(self.sc)
        self.H, self.W = self.veg_s.shape
        rng = np.random.RandomState(12345)
        self.seeds = [int(s) for s in rng.randint(1, 2**31 - 1, size=n_seeds)]
        self.yaws = [float(y) for y in np.arange(0, 360, 360.0 / n_yaws)]
        self.ages = ages
        self.table_seeds = table_seeds
        self.workers = workers
        self.workdir = workdir or os.path.join(TR.PROJECT, "twin_work", "stage1_opt")
        self.log = log
        self.regions = {}
        self.real_leaflets = {}
        for c in self.plants:
            mask = self.labels_s == c["label"]
            r = int(np.sqrt(mask.sum() / np.pi))
            self.regions[c["label"]] = (mask, cv2.dilate(mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))) > 0)
            w, n = leaflet_stats(mask)
            self.real_leaflets[c["label"]] = (float(np.median(w)) if len(w) else 0.0, n)
        #: weights of the leaflet-width and leaflet-count terms (|log ratio| per plant) against IoU
        self.w_width = 0.30
        self.w_count = 0.15

    def footprint_table(self, ov, tag):
        cands = [dict(x=0.0, y=0.0, yaw_deg=0.0, age=float(a), seed=int(s)) for a in self.ages for s in self.table_seeds]
        res = rasterize_many(ov, cands, os.path.join(self.workdir, "tab"), self.workers, chunk=len(self.table_seeds) * 3, tag=tag)
        table = {}
        i = 0
        for a in self.ages:
            areas = [int(res[i + j][0].sum()) for j in range(len(self.table_seeds))]
            i += len(self.table_seeds)
            table[float(a)] = dict(mean=float(np.mean(areas)), std=float(np.std(areas)), areas=areas)
        return table

    def __call__(self, params, tag="t"):
        """params: dict of config overrides. Returns (mean best IoU, per-plant best IoUs, ages)."""
        t0 = time.time()
        ov = dict(self.base_ov)
        ov.update(params)
        cam_h = float(ov.get("camera.height", R.CAMERA_HEIGHT_M))
        table = self.footprint_table(ov, tag + "tab")
        cands, index = [], []
        ages = []
        for pi, c in enumerate(self.plants):
            age = F.invert_footprint(table, c["area_px"] * self.sc * self.sc)
            ages.append(age)
            bx, by = R.ground_xy(c["x"], c["y"], camera_height_m=cam_h)
            for s in self.seeds:
                for y in self.yaws:
                    cands.append(dict(x=bx, y=by, yaw_deg=y, age=age, seed=s))
                    index.append(pi)
        res = rasterize_many(ov, cands, os.path.join(self.workdir, "cand"), self.workers, chunk=len(self.yaws) * 2, tag=tag)
        best = [0.0] * len(self.plants)
        best_mask = [None] * len(self.plants)
        for pi, (veg, x0, y0) in zip(index, res):
            mask, region = self.regions[self.plants[pi]["label"]]
            v = F.score_candidate(F.place(veg, x0, y0, self.W, self.H), mask, region)
            if v > best[pi]:
                best[pi] = v
                best_mask[pi] = (veg, x0, y0)
        # leaflet width and count of the chosen candidate against the real plant
        width_pen, count_pen = [], []
        for pi, bm in enumerate(best_mask):
            rw, rn = self.real_leaflets[self.plants[pi]["label"]]
            if bm is None or rw <= 0 or rn == 0:
                width_pen.append(1.0); count_pen.append(1.0); continue
            w, n = leaflet_stats(bm[0])
            sw = float(np.median(w)) if len(w) else 1e-3
            width_pen.append(abs(np.log(max(sw, 1e-3) / rw)))
            count_pen.append(abs(np.log(max(n, 1) / rn)))
        iou_mean = float(np.mean(best))
        score = iou_mean - self.w_width * float(np.mean(width_pen)) - self.w_count * float(np.mean(count_pen))
        self.log(f"  [{tag}] score {score:.4f} = IoU {iou_mean:.4f} - width {np.mean(width_pen):.3f} - count {np.mean(count_pen):.3f}  per plant IoU {np.round(best, 3).tolist()}  ages {np.round(ages, 1).tolist()}  ({time.time() - t0:.0f} s)")
        self.last = dict(iou=iou_mean, width_pen=float(np.mean(width_pen)), count_pen=float(np.mean(count_pen)))
        return score, best, ages


# ------------------------------------------------------------- parameters ---

#: Search space: (low, high) for Optuna floats. Ranges for "min" values; the paired "max" is
#: min + a width drawn separately so min <= max always holds.
SPACE = {
    "leaf.prototype_scale_min": (0.04, 0.12),
    "leaf.prototype_scale_width": (0.005, 0.06),
    "leaf.petiole_length_min": (0.02, 0.12),
    "leaf.petiole_length_width": (0.005, 0.05),
    "leaf.petiole_pitch_min": (0.0, 60.0),
    "leaf.petiole_pitch_width": (5.0, 40.0),
    "leaf.pitch_std": (3.0, 40.0),
    "canopy.phyllochron": (0.7, 3.0),
    "canopy.internode_length_max": (0.01, 0.06),
    "leaf.angle_beta_mu": (0.8, 3.0),
    "leaf.angle_beta_nu": (0.8, 3.0),
    "camera.height": (1.48, 1.66),
}


def to_overrides(x):
    """Optuna sample -> config overrides."""
    o = {
        "leaf.prototype_scale_min": x["leaf.prototype_scale_min"],
        "leaf.prototype_scale_max": x["leaf.prototype_scale_min"] + x["leaf.prototype_scale_width"],
        "leaf.petiole_length_min": x["leaf.petiole_length_min"],
        "leaf.petiole_length_max": x["leaf.petiole_length_min"] + x["leaf.petiole_length_width"],
        "leaf.petiole_pitch_min": x["leaf.petiole_pitch_min"],
        "leaf.petiole_pitch_max": x["leaf.petiole_pitch_min"] + x["leaf.petiole_pitch_width"],
        "leaf.pitch_std": x["leaf.pitch_std"],
        "canopy.phyllochron": x["canopy.phyllochron"],
        "canopy.internode_length_max": x["canopy.internode_length_max"],
        "leaf.set_angle_distribution": 1,
        "leaf.angle_beta_mu": x["leaf.angle_beta_mu"],
        "leaf.angle_beta_nu": x["leaf.angle_beta_nu"],
        "camera.height": x["camera.height"],
    }
    return {k: (round(v, 5) if isinstance(v, float) else v) for k, v in o.items()}


#: The library / previous-project defaults, as the first trial so the optimiser starts from what
#: the sparse fit used and every later trial is measured against it.
DEFAULTS = {
    "leaf.prototype_scale_min": 0.10, "leaf.prototype_scale_width": 0.06,
    "leaf.petiole_length_min": 0.10, "leaf.petiole_length_width": 0.04,
    "leaf.petiole_pitch_min": 20.0, "leaf.petiole_pitch_width": 30.0,
    "leaf.pitch_std": 20.0, "canopy.phyllochron": 2.0, "canopy.internode_length_max": 0.025,
    "leaf.angle_beta_mu": 1.0, "leaf.angle_beta_nu": 1.0, "camera.height": 1.55,
}


# ------------------------------------------------------ leaf shape and posture ---

class LeafShapeObjective(Stage1Objective):
    """Stage 1 with leaf-level terms: the best-IoU candidate of each plant is also measured leaflet by leaflet.

    Terms, each against the real frame (see twin/leaflets.py for the measures):
      IoU           mean best per-plant silhouette IoU, as before
      length, width |log ratio| of the pooled median visible-leaflet length and width
      thin          |difference| of the mean thin-structure fraction (petioles and stems)
      count         |log ratio| of visible leaflets per plant (weight 0 by default: SAM finds about half the real leaflets, so
                    the real count is a floor, not a target; it is logged)
    `targets` holds the real frame's values already converted to the raster's terms (SAM's bias removed using the check on
    the rendered twin), as dict(major=, minor=, thin=, n_per_plant=)."""

    def __init__(self, target, base_ov, targets, weights=None, **kw):
        super().__init__(target, base_ov, **kw)
        self.leaf_targets = targets
        self.weights = dict(length=0.3, width=0.3, thin=1.0, count=0.0)
        if weights:
            self.weights.update(weights)

    def __call__(self, params, tag="t"):
        from . import leaflets as L
        t0 = time.time()
        ov = dict(self.base_ov)
        ov.update(params)
        cam_h = float(ov.get("camera.height", R.CAMERA_HEIGHT_M))
        table = self.footprint_table(ov, tag + "tab")
        cands, index, ages = [], [], []
        for pi, c in enumerate(self.plants):
            age = F.invert_footprint(table, c["area_px"] * self.sc * self.sc)
            ages.append(age)
            bx, by = R.ground_xy(c["x"], c["y"], camera_height_m=cam_h)
            for s in self.seeds:
                for y in self.yaws:
                    cands.append(dict(x=bx, y=by, yaw_deg=y, age=age, seed=s))
                    index.append(pi)
        res = rasterize_many(ov, cands, os.path.join(self.workdir, "cand"), self.workers, chunk=len(self.yaws) * 2, tag=tag, with_maps=True)
        best = [0.0] * len(self.plants)
        best_maps = [None] * len(self.plants)
        for pi, (veg, x0, y0, obj, cls) in zip(index, res):
            mask, region = self.regions[self.plants[pi]["label"]]
            v = F.score_candidate(F.place(veg, x0, y0, self.W, self.H), mask, region)
            if v > best[pi]:
                best[pi] = v
                best_maps[pi] = (veg, obj, cls)
        segments, thin, counts = [], [], []
        for bm in best_maps:
            if bm is None:
                thin.append(1.0)
                counts.append(0)
                continue
            segs = L.synthetic_leaflets(bm[1], bm[2], scale=1.0 / self.sc)
            segments += segs
            counts.append(len(segs))
            thin.append(L.thin_fraction(bm[0]))
        syn = L.summarise(segments)
        tg = self.leaf_targets
        pen = dict(length=abs(np.log(max(syn["major"], 1e-3) / tg["major"])), width=abs(np.log(max(syn["minor"], 1e-3) / tg["minor"])),
                   thin=abs(float(np.mean(thin)) - tg["thin"]), count=abs(np.log(max(float(np.mean(counts)), 0.5) / tg["n_per_plant"])))
        iou_mean = float(np.mean(best))
        score = iou_mean - sum(self.weights[k] * pen[k] for k in pen)
        self.last = dict(iou=iou_mean, penalties=pen, synthetic=dict(major=syn["major"], minor=syn["minor"], thin=float(np.mean(thin)), n_per_plant=float(np.mean(counts))))
        self.log(f"  [{tag}] score {score:.4f} = IoU {iou_mean:.4f} - " + " - ".join(f"{k} {pen[k]:.3f}" for k in pen)
                 + f"  | leaflet {syn['major']:.1f}x{syn['minor']:.1f} px (target {tg['major']:.1f}x{tg['minor']:.1f}), thin {np.mean(thin):.3f} ({tg['thin']:.3f}), "
                 f"n/plant {np.mean(counts):.1f} ({tg['n_per_plant']:.1f})  ({time.time() - t0:.0f} s)")
        return score, best, ages


#: Leaf-shape search: the silhouette parameters that stayed identified, the leaflet shape and posture parameters the harness now
#: exposes, and camera height and leaf pitch spread fixed (not identified, and leaf elevation is set by the Beta distribution).
SHAPE_SPACE = {
    "leaf.prototype_scale_min": (0.04, 0.14),
    "leaf.prototype_scale_width": (0.005, 0.06),
    "leaf.petiole_length_min": (0.01, 0.12),
    "leaf.petiole_length_width": (0.005, 0.05),
    "leaf.petiole_pitch_min": (0.0, 60.0),
    "leaf.petiole_pitch_width": (5.0, 40.0),
    "canopy.phyllochron": (0.7, 3.0),
    "canopy.internode_length_max": (0.005, 0.06),
    "leaf.angle_beta_mu": (0.8, 3.0),
    "leaf.angle_beta_nu": (0.8, 3.0),
    "leaf.aspect_ratio": (0.4, 1.2),
    "leaf.midrib_fold_fraction": (0.0, 0.4),
    "leaf.lateral_curvature": (-0.6, 0.2),
    "leaf.longitudinal_curvature_max": (-0.4, 0.1),
    "leaf.leaflet_offset": (0.1, 0.8),
    "leaf.leaflet_scale": (0.6, 1.0),
    "leaf.petiole_curvature_max": (-200.0, 0.0),
    "canopy.internode_pitch": (0.0, 60.0),
}

SHAPE_FIXED = {"camera.height": 1.55355, "leaf.pitch_std": 27.64961, "leaf.set_angle_distribution": 1}


def shape_overrides(x):
    """Optuna sample from SHAPE_SPACE -> config overrides."""
    o = dict(SHAPE_FIXED)
    o.update({
        "leaf.prototype_scale_min": x["leaf.prototype_scale_min"],
        "leaf.prototype_scale_max": x["leaf.prototype_scale_min"] + x["leaf.prototype_scale_width"],
        "leaf.petiole_length_min": x["leaf.petiole_length_min"],
        "leaf.petiole_length_max": x["leaf.petiole_length_min"] + x["leaf.petiole_length_width"],
        "leaf.petiole_pitch_min": x["leaf.petiole_pitch_min"],
        "leaf.petiole_pitch_max": x["leaf.petiole_pitch_min"] + x["leaf.petiole_pitch_width"],
        "canopy.phyllochron": x["canopy.phyllochron"],
        "canopy.internode_length_max": x["canopy.internode_length_max"],
        "leaf.angle_beta_mu": x["leaf.angle_beta_mu"],
        "leaf.angle_beta_nu": x["leaf.angle_beta_nu"],
        "leaf.aspect_ratio": x["leaf.aspect_ratio"],
        "leaf.midrib_fold_fraction": x["leaf.midrib_fold_fraction"],
        "leaf.lateral_curvature": x["leaf.lateral_curvature"],
        "leaf.longitudinal_curvature_min": x["leaf.longitudinal_curvature_max"] - 0.2,
        "leaf.longitudinal_curvature_max": x["leaf.longitudinal_curvature_max"],
        "leaf.leaflet_offset": x["leaf.leaflet_offset"],
        "leaf.leaflet_scale": x["leaf.leaflet_scale"],
        "leaf.petiole_curvature_min": x["leaf.petiole_curvature_max"] - 150.0,
        "leaf.petiole_curvature_max": x["leaf.petiole_curvature_max"],
        "canopy.internode_pitch": x["canopy.internode_pitch"],
    })
    return {k: (round(v, 5) if isinstance(v, float) else v) for k, v in o.items()}


#: Two starting points: the leaflet-aware fit's parameters with the library's leaf shape (what the current twins use), and the
#: same with the library's silhouette parameters.
SHAPE_STARTS = [
    {"leaf.prototype_scale_min": 0.05315, "leaf.prototype_scale_width": 0.05225, "leaf.petiole_length_min": 0.08092, "leaf.petiole_length_width": 0.04138,
     "leaf.petiole_pitch_min": 32.56851, "leaf.petiole_pitch_width": 16.34157, "canopy.phyllochron": 0.96251, "canopy.internode_length_max": 0.01536,
     "leaf.angle_beta_mu": 2.25995, "leaf.angle_beta_nu": 2.08915, "leaf.aspect_ratio": 0.7, "leaf.midrib_fold_fraction": 0.2, "leaf.lateral_curvature": -0.4,
     "leaf.longitudinal_curvature_max": -0.1, "leaf.leaflet_offset": 0.4, "leaf.leaflet_scale": 0.9, "leaf.petiole_curvature_max": -50.0, "canopy.internode_pitch": 20.0},
    {"leaf.prototype_scale_min": 0.10, "leaf.prototype_scale_width": 0.02, "leaf.petiole_length_min": 0.06, "leaf.petiole_length_width": 0.02,
     "leaf.petiole_pitch_min": 45.0, "leaf.petiole_pitch_width": 15.0, "canopy.phyllochron": 2.0, "canopy.internode_length_max": 0.025,
     "leaf.angle_beta_mu": 1.0, "leaf.angle_beta_nu": 1.0, "leaf.aspect_ratio": 0.7, "leaf.midrib_fold_fraction": 0.2, "leaf.lateral_curvature": -0.4,
     "leaf.longitudinal_curvature_max": -0.1, "leaf.leaflet_offset": 0.4, "leaf.leaflet_scale": 0.9, "leaf.petiole_curvature_max": -50.0, "canopy.internode_pitch": 20.0},
]
