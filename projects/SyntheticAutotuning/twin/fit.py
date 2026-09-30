"""Staged fit of one synthetic scene to one real frame, on the rasterized proxy.

Stages, each closing one source of mismatch with the cheapest instrument that can see it:

  1. per-plant SIZE      -- the model's age-to-footprint curve inverts each real plant's
                            footprint area into an age (the generator has no per-plant size
                            knob other than age, and age is what a seedling's size means)
  2. LAYOUT              -- plant positions come from the photo (bed coordinates through the
                            calibrated pinhole), never from a grid draw
  3. per-plant REALISATION -- for each site, K candidate seeds x a yaw sweep, scored by the
                            IoU of the candidate's silhouette against the real plant's mask;
                            plants are independent (per-site streams, no competition), so
                            the search factorises: K*N rasterizations instead of K^N scenes
  4. per-plant refinement -- age +-, yaw fine sweep, with the rest of the scene frozen

Everything here is geometry; appearance (lighting, leaf optics, camera pipeline) is fitted
afterwards on the ray tracer with this geometry frozen, which makes it deterministic.
"""
import json
import os
import time

import cv2
import numpy as np

from . import raster as TR
from . import real as R

#: Generator settings shared by every stage. Camera from the rover calibration; procedural
#: leaves and no nitrogen model because the proxy needs neither; per-site random streams on.
BASE = {
    "camera.hfov": round(R.HFOV_DEG, 3),
    "camera.height": 1.55,
    "leaf.use_obj_mesh": 0,
    "leaf.nitrogen_model": 0,
    "scene.load_rover": 0,
    "canopy.per_plant_seed": 1,
    "raster.scale": 0.5,
}


def px_scale(ov):
    return float(ov.get("raster.scale", 1.0))


# ---------------------------------------------------------------- target ---

class Target:
    """One real frame and everything measured from it."""

    def __init__(self, path, workdir, undistort=True, veg_mask=None, rover_mask=None):
        self.path = path
        self.workdir = workdir
        os.makedirs(workdir, exist_ok=True)
        # A rendered image is already a pinhole image and must not be undistorted.
        self.rgb = R.load(path) if undistort else cv2.cvtColor(cv2.imread(path, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
        rover = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "calib", "rover_mask.npy")
        if rover_mask is not None:
            self.rover = rover_mask
        else:
            self.rover = np.load(rover) if os.path.exists(rover) else R.rover_mask(self.rgb)
        self.valid = ~self.rover
        self.veg = (veg_mask if veg_mask is not None else R.vegetation_mask(self.rgb)) & self.valid
        self.cover = float(self.veg.sum() / self.valid.sum())
        self.rows, _ = R.find_rows(self.veg, self.rover)
        n, self.labels, self.stats, self.centroids = cv2.connectedComponentsWithStats(self.veg.astype(np.uint8), connectivity=8)
        self.n_components = n

    def components(self, min_area_px=1500):
        """Real plant footprints as connected components (sparse stands only)."""
        out = []
        for k in range(1, self.n_components):
            x, y, w, h, a = self.stats[k]
            if a < min_area_px:
                continue
            out.append(dict(label=int(k), x=float(self.centroids[k][0]), y=float(self.centroids[k][1]),
                            area_px=float(a), bbox=(int(x), int(y), int(w), int(h))))
        return out

    def plants(self, min_area_px=1500, min_sep_px=90, smooth_px=25):
        """Individual plants: connected components, split along the row direction where the
        component's width profile shows more than one plant.

        Seedlings in a row touch long before the canopy closes, so a component is often two
        or three plants. Rows run top-to-bottom in the frame, so a component's width per image
        row (pixels across the row) is a 1-D profile with one bump per plant; its peaks,
        separated by at least the sowing spacing, are the plants, and each pixel goes to the
        nearest peak along the row. Returns dicts with a per-plant label image `self.plant_labels`.
        """
        H, W = self.veg.shape
        self.plant_labels = np.zeros((H, W), np.int32)
        out = []
        k = np.exp(-0.5 * (np.arange(-3 * smooth_px, 3 * smooth_px + 1) / smooth_px) ** 2)
        k /= k.sum()
        for c in self.components(min_area_px):
            x, y, w, h = c["bbox"]
            sub = self.labels[y : y + h, x : x + w] == c["label"]
            prof = np.convolve(sub.sum(1).astype(float), k, mode="same")
            peaks = []
            for i in range(1, len(prof) - 1):
                if prof[i] >= prof[i - 1] and prof[i] >= prof[i + 1] and prof[i] > 0.25 * prof.max():
                    if not peaks or i - peaks[-1] >= min_sep_px:
                        peaks.append(i)
                    elif prof[i] > prof[peaks[-1]]:
                        peaks[-1] = i
            if not peaks:
                peaks = [int(np.argmax(prof))]
            rows_idx = np.arange(h)[:, None]
            nearest = np.argmin(np.abs(rows_idx - np.array(peaks)[None, :]), axis=1)
            for j, pk in enumerate(peaks):
                part = sub & (nearest[:, None] == j)
                a = int(part.sum())
                if a < min_area_px // 3:
                    continue
                ys, xs = np.nonzero(part)
                lab = len(out) + 1
                self.plant_labels[y + ys, x + xs] = lab
                out.append(dict(label=lab, x=float(x + xs.mean()), y=float(y + ys.mean()), area_px=float(a),
                                component=c["label"], bbox=(int(x + xs.min()), int(y + ys.min()), int(np.ptp(xs) + 1), int(np.ptp(ys) + 1))))
        return out

    def downsampled(self, scale):
        """Vegetation and validity masks at the rasterizer's scale (the frame's own size: the T4 frame is
        R.WIDTH x R.HEIGHT, a synthetic benchmark frame 720 x 720)."""
        H0, W0 = self.veg.shape
        w, h = int(round(W0 * scale)), int(round(H0 * scale))
        veg = cv2.resize(self.veg.astype(np.uint8), (w, h), interpolation=cv2.INTER_AREA) > 0.5
        valid = cv2.resize(self.valid.astype(np.uint8), (w, h), interpolation=cv2.INTER_AREA) > 0.5
        src = getattr(self, "plant_labels", self.labels)
        labels = cv2.resize(src.astype(np.float32), (w, h), interpolation=cv2.INTER_NEAREST).astype(np.int32)
        return veg, valid, labels


# ----------------------------------------------------------- generator ---

def single_plant(ov, age, seed, x=0.0, y=0.0, yaw_deg=0.0, workdir=None, base=None):
    """Rasterize one plant alone at (x, y): cropped maps plus the crop offset."""
    workdir = os.path.abspath(workdir or os.path.join(TR.PROJECT, "twin_work", "single"))
    os.makedirs(workdir, exist_ok=True)
    base = base or f"p_{int(seed)}_{age:.1f}_{yaw_deg:.1f}"
    layout = os.path.join(workdir, base + "_layout.txt")
    TR.write_layout(layout, [dict(x=x, y=y, yaw_deg=yaw_deg, age=age, seed=seed)])
    o = dict(ov)
    o["canopy.layout_file"] = layout
    o["raster.crop"] = 1
    o["raster.ground"] = 0
    m = TR.run(o, seed=1, folder=workdir, base=base)
    os.remove(layout)
    return m


def footprint_table(ov, ages, seeds, workdir):
    """Footprint area (px^2 at raster.scale, plant at the frame centre) per age and seed."""
    table = {}
    t0 = time.time()
    for age in ages:
        areas = []
        for s in seeds:
            m = single_plant(ov, age, s, workdir=workdir, base=f"fp_{age:.0f}_{s}")
            areas.append(int(m.vegetation.sum()))
        table[float(age)] = dict(mean=float(np.mean(areas)), std=float(np.std(areas)), areas=areas)
        print(f"  age {age:5.1f}: footprint {np.mean(areas):8.0f} +- {np.std(areas):6.0f} px  ({len(areas)} seeds)", flush=True)
    print(f"footprint table: {len(ages)} ages x {len(seeds)} seeds in {time.time() - t0:.0f} s", flush=True)
    return table


def invert_footprint(table, area_px):
    """Age whose mean footprint is nearest to area_px (log interpolation between ages)."""
    ages = np.array(sorted(table))
    means = np.array([table[a]["mean"] for a in ages])
    if area_px <= means[0]:
        return float(ages[0])
    if area_px >= means[-1]:
        return float(ages[-1])
    k = int(np.searchsorted(means, area_px))
    a0, a1, m0, m1 = ages[k - 1], ages[k], means[k - 1], means[k]
    t = (np.log(area_px) - np.log(m0)) / max(np.log(m1) - np.log(m0), 1e-9)
    return float(a0 + t * (a1 - a0))


# ------------------------------------------------------------ scoring ---

def place(mask_crop, x0, y0, W, H):
    out = np.zeros((H, W), bool)
    h, w = mask_crop.shape
    out[y0 : y0 + h, x0 : x0 + w] = mask_crop
    return out


def iou(a, b):
    u = (a | b).sum()
    return float((a & b).sum() / u) if u else 0.0


def rotate_mask(mask, angle_deg, centre):
    """Rotate a boolean mask about a pixel centre (approximation of a yaw change: exact only
    for an orthographic camera, close enough at these working distances to rank candidates;
    the chosen yaw is re-rasterized before it is used)."""
    M = cv2.getRotationMatrix2D((float(centre[0]), float(centre[1])), angle_deg, 1.0)
    return cv2.warpAffine(mask.astype(np.uint8), M, (mask.shape[1], mask.shape[0]), flags=cv2.INTER_NEAREST) > 0


def score_candidate(cand, target_mask, region):
    """IoU inside a region of interest (the real plant's neighbourhood)."""
    return iou(cand & region, target_mask & region)


# ------------------------------------------------------------ parallel ---

def _cand_job(args):
    ov, age, seed, x, y, yaw, workdir, base = args
    m = single_plant(ov, age, seed, x, y, yaw, workdir=workdir, base=base)
    return (m.vegetation.copy(), m.x0, m.y0)


def candidates(ov, jobs, workers=6):
    """Rasterize many single plants: jobs are (age, seed, x, y, yaw, workdir, base).

    Batched through the rasterizer's per-site mode (`raster.each_site`): one process builds and
    draws a chunk of plants, which amortises start-up and asset loading, the actual cost of a
    single plant as its own process."""
    if not jobs:
        return []
    cands = [dict(x=j[2], y=j[3], yaw_deg=j[4], age=j[0], seed=j[1]) for j in jobs]
    return TR.rasterize_many(ov, cands, jobs[0][5], workers=workers, chunk=16, tag="c")


# --------------------------------------------------------------- stages ---

def region_of(real_mask):
    """A real plant's neighbourhood, one plant radius wide, inside which a candidate is scored."""
    r = int(np.sqrt(real_mask.sum() / np.pi))
    return cv2.dilate(real_mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))) > 0


def refine_sites(sites, labels_s, ov, cand_dir, ages, yaw_step_deg, W, H, workers=6, log=print, age_steps=None):
    """Stage 4: age, yaw and position refined per site with its seed fixed. Updates the sites in place.

    `age_steps` overrides the age offsets tried, so a caller holding age fixed passes (0.0,)."""
    t0 = time.time()
    for k, s in enumerate(sites):
        real_mask = labels_s == s["label"]
        region = region_of(real_mask)
        jobs, keys = [], []
        for dage in (age_steps if age_steps is not None else (-3.0, -1.5, 0.0, 1.5, 3.0)):
            for dyaw in (-yaw_step_deg / 3, 0.0, yaw_step_deg / 3):
                for dx, dy in ((0, 0), (0.02, 0), (-0.02, 0), (0, 0.02), (0, -0.02)):
                    age = min(max(min(ages), s["age"] + dage), max(ages))
                    yaw = (s["yaw_deg"] + dyaw) % 360
                    keys.append((age, yaw, s["x"] + dx, s["y"] + dy))
                    jobs.append((age, s["seed"], s["x"] + dx, s["y"] + dy, yaw, cand_dir, f"r{k}_{len(jobs)}"))
        res = candidates(ov, jobs, workers)
        best = (s["iou"], s["age"], s["yaw_deg"], s["x"], s["y"])
        for (age, yaw, x, y), (veg, x0, y0) in zip(keys, res):
            v = score_candidate(place(veg, x0, y0, W, H), real_mask, region)
            if v > best[0]:
                best = (v, age, yaw, x, y)
        log(f"  site {k:2d} refined: IoU {s['iou']:.3f} -> {best[0]:.3f}  age {s['age']:.1f}->{best[1]:.1f} yaw {s['yaw_deg']:.0f}->{best[2]:.0f}")
        s["iou"], s["age"], s["yaw_deg"], s["x"], s["y"] = best
    log(f"stage 4: refinement in {time.time() - t0:.0f} s")


def fit_sparse(target, ov, workdir, ages=(6, 8, 10, 12, 14, 16, 18, 20, 23, 26, 30, 35, 40, 46), n_seeds=12,
               yaw_step_deg=30, table_seeds=(1, 2, 3, 4), min_area_px=1500, refine=True, workers=6, log=print, scores=None,
               pin_age=None, pin_age_jitter=0.0, camera=None, min_sep_px=90, plants=None):
    """Stages 1-4 for a stand whose plants are separable (after row-wise splitting) in the mask.

    `pin_age` starts every plant at that age instead of reading it off its footprint; `pin_age_jitter` is how far stage 4
    may then move an individual plant from it, which keeps the stand centred on its true age while still letting plants
    differ in vigour the way a real stand does. A jitter of 0 holds every plant exactly. Age
    and leaf production trade against each other through footprint area -- a plant with more leaves matches the same
    outline younger -- so neither is identifiable while both are free. The stand's own emergence date pins the age from
    outside the fit: five independent fits across three dates recovered 2023-06-08 within two days.

    I/O (2026-09-29, block C), all defaulting to the T4 rover frame: `camera` = dict(fx=, width=, height=) for a frame
    from another pinhole camera (a synthetic benchmark view); `min_sep_px` the in-row plant separation of the splitting;
    `plants` a plant list in Target.plants() form (with target.plant_labels set) when the plants are given rather than
    split from the mask (a one-plant scene).

    If `scores` is a dict, stage 3 stores every candidate's IoU in it: scores["iou"][k] is a (n_seeds, n_yaws) list for site k,
    with the seeds in scores["seeds"][k] and the yaws in scores["yaws"]."""
    sc = px_scale(ov)
    plants = target.plants(min_area_px, min_sep_px=min_sep_px) if plants is None else plants
    veg_s, valid_s, labels_s = target.downsampled(sc)
    cam = {} if camera is None else dict(fx=camera["fx"], width=camera["width"], height=camera["height"])
    H, W = veg_s.shape
    log(f"target: cover {target.cover:.3f}, {len(plants)} plants after splitting, rows at {target.rows}")

    # Stage 1: age from footprint, or held at the stand's own age --------------------
    table = {} if pin_age is not None else footprint_table(ov, ages, table_seeds, os.path.join(workdir, "table"))
    sites = []
    for c in plants:
        area_s = c["area_px"] * sc * sc
        age = float(pin_age) if pin_age is not None else invert_footprint(table, area_s)
        bx, by = R.ground_xy(c["x"], c["y"], camera_height_m=ov["camera.height"], **cam)
        sites.append(dict(x=bx, y=by, yaw_deg=0.0, age=age, seed=0, label=c["label"], px=c["x"] * sc, py=c["y"] * sc, area_s=area_s))
    log("stage 1: ages " + " ".join(f"{s['age']:.0f}" for s in sites))

    # Stage 3: seed and yaw per site, every candidate rasterized exactly ------------
    rng = np.random.RandomState(0)
    cand_dir = os.path.join(workdir, "cand")
    t0 = time.time()
    yaws = np.arange(0, 360, yaw_step_deg)
    if scores is not None:
        scores.update(iou=[], seeds=[], yaws=[float(y) for y in yaws])
    for k, s in enumerate(sites):
        real_mask = labels_s == s["label"]
        region = region_of(real_mask)
        seeds = rng.randint(1, 2**31 - 1, size=n_seeds)
        jobs = [(s["age"], int(seed), s["x"], s["y"], float(yaw), cand_dir, f"c{k}_{seed}_{int(yaw)}") for seed in seeds for yaw in yaws]
        res = candidates(ov, jobs, workers)
        best = (-1.0, None, None)
        site_scores = []
        for (age, seed, x, y, yaw, _, _), (veg, x0, y0) in zip(jobs, res):
            v = score_candidate(place(veg, x0, y0, W, H), real_mask, region)
            site_scores.append(v)
            if v > best[0]:
                best = (v, seed, yaw)
        if scores is not None:
            scores["iou"].append(np.array(site_scores).reshape(len(seeds), len(yaws)).tolist())
            scores["seeds"].append([int(x) for x in seeds])
        s["seed"], s["yaw_deg"], s["iou"] = best[1], best[2], best[0]
        log(f"  site {k:2d}: age {s['age']:4.1f} seed {s['seed']:10d} yaw {s['yaw_deg']:5.1f}  IoU {best[0]:.3f}")
    log(f"stage 3: {len(sites)} sites x {n_seeds} seeds x {len(yaws)} yaws in {time.time() - t0:.0f} s")

    # Stage 4: local refinement of age, yaw and position with the seed fixed ---------
    if refine:
        steps = None
        if pin_age is not None:
            j = float(pin_age_jitter)
            steps = (0.0,) if j <= 0 else (-j, -j / 2, 0.0, j / 2, j)
        refine_sites(sites, labels_s, ov, cand_dir, ages, yaw_step_deg, W, H, workers, log, age_steps=steps)

    layout = os.path.join(workdir, "layout.txt")
    TR.write_layout(layout, sites)
    json.dump(dict(sites=sites, table=table, overrides=ov, target=target.path), open(os.path.join(workdir, "fit.json"), "w"), indent=1)
    return sites, layout


def evaluate_layout(target, ov, layout, workdir, base="scene"):
    """Full-scene raster of a layout against the real frame: global vegetation IoU, cover."""
    o = dict(ov)
    o["canopy.layout_file"] = layout
    m = TR.run(o, seed=1, folder=workdir, base=base)
    sc = px_scale(ov)
    veg_s, valid_s, _ = target.downsampled(sc)
    syn = m.vegetation & valid_s
    real = veg_s & valid_s
    return dict(iou=iou(syn, real), cover_real=float(real.sum() / valid_s.sum()), cover_syn=float(syn.sum() / valid_s.sum()),
                precision=float((syn & real).sum() / max(syn.sum(), 1)), recall=float((syn & real).sum() / max(real.sum(), 1))), m


def overlay(target, maps, path, scale=None):
    """Real frame with the synthetic vegetation outline drawn on it, for the eye."""
    sc = scale or maps.W / R.WIDTH
    rgb = cv2.resize(target.rgb, (maps.W, maps.H), interpolation=cv2.INTER_AREA)
    syn = maps.full("class", 255)
    veg = np.isin(syn, TR.VEG_CLASSES).astype(np.uint8)
    edges = cv2.morphologyEx(veg, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)) > 0
    out = rgb.copy()
    out[edges] = (255, 0, 255)
    cv2.imwrite(path, cv2.cvtColor(out, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 90])
    return out
