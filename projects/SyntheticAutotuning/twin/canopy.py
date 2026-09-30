"""Closed-canopy stage: per-site realisation when the vegetation mask is saturated.

Once the rows close, a plant's silhouette is no longer visible and the mask carries almost no
information; what the photo still shows is the ARRANGEMENT of the top leaves -- their outlines,
their sizes, which way each faces -- and the gaps. Three cues that the rasterizer can produce
without light transport are compared inside a window around each site:

  * vegetation IoU          (the gaps: soil where the photo shows soil)
  * edge agreement          (leaf outlines: chamfer distance between real intensity edges and
                             synthetic organ boundaries, both ways)
  * shading correlation     (leaf orientation: normalised cross-correlation between the real
                             luminance and the synthetic n.z, a Lambertian proxy for a light
                             rig at nadir)

Occlusion couples neighbouring sites, so a candidate is not scored alone: it is composited by
depth against the rest of the scene rasterized without that site, which gives the exact
full-scene maps for the candidate at the cost of one single-plant pass.

Layout for a closed canopy comes from the row geometry and the sowing spacing (a prior; the
positions are not identifiable from the mask) with per-site presence, age, seed, yaw and
along-row position fitted by coordinate descent over sites.
"""
import json
import os
import time

import cv2
import numpy as np

from . import fit as F
from . import raster as TR
from . import real as R


# ------------------------------------------------------------ compositing ---

class Scene:
    """Full-frame maps at raster scale with a depth buffer, so plants can be composited."""

    def __init__(self, maps=None, W=None, H=None):
        if maps is not None:
            self.W, self.H = maps.W, maps.H
            self.depth = maps.full("depth", np.inf).astype(np.float32)
            self.cls = maps.full("class", 255)
            self.site = maps.full("site", 0)
            self.obj = maps.full("obj", 0)
            self.normal = maps.full("normal", 0.0)
        else:
            self.W, self.H = W, H
            self.depth = np.full((H, W), np.inf, np.float32)
            self.cls = np.full((H, W), 255, np.uint8)
            self.site = np.zeros((H, W), np.uint16)
            self.obj = np.zeros((H, W), np.uint32)
            self.normal = np.zeros((H, W, 3), np.float32)

    def copy(self):
        s = Scene(W=self.W, H=self.H)
        s.depth, s.cls, s.site, s.obj, s.normal = self.depth.copy(), self.cls.copy(), self.site.copy(), self.obj.copy(), self.normal.copy()
        return s

    def composite(self, cand, site_index):
        """Return a copy with a cropped single-plant raster (Maps) z-tested into it."""
        s = self.copy()
        h, w = cand.arrays["class"].shape
        y0, x0 = cand.y0, cand.x0
        sl = (slice(y0, y0 + h), slice(x0, x0 + w))
        cd = cand.arrays["depth"]
        cc = cand.arrays["class"]
        win = (cc != 255) & (cd < s.depth[sl])
        s.depth[sl][win] = cd[win]
        s.cls[sl][win] = cc[win]
        s.site[sl][win] = site_index
        s.obj[sl][win] = cand.arrays["obj"][win]
        s.normal[sl][win] = cand.arrays["normal"][win]
        return s

    @property
    def vegetation(self):
        return np.isin(self.cls, TR.VEG_CLASSES)


def scene_without(ov, layout_sites, k, workdir, base):
    """Rasterize every site except k (or all, k=None) at full frame."""
    o = dict(ov)
    lay = os.path.join(workdir, base + "_layout.txt")
    TR.write_layout(lay, layout_sites)
    o["canopy.layout_file"] = lay
    if k is not None:
        keep = [str(i) for i in range(len(layout_sites)) if i != k]
        o["raster.only_sites"] = ",".join(keep) if keep else "-1"
    return Scene(TR.run(o, seed=1, folder=workdir, base=base))


# --------------------------------------------------------------- scoring ---

class RealCues:
    """Per-pixel cues from the real frame at raster scale: luminance, edges, vegetation."""

    def __init__(self, target, scale, canny=(40, 100)):
        w, h = int(round(R.WIDTH * scale)), int(round(R.HEIGHT * scale))
        rgb = cv2.resize(target.rgb, (w, h), interpolation=cv2.INTER_AREA)
        self.veg, self.valid, self.labels = target.downsampled(scale)
        lab = R.lab(rgb)
        self.L = lab[..., 0].astype(np.float32)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        self.edges = cv2.Canny(gray, canny[0], canny[1]) > 0
        self.edges &= self.valid
        self.edge_dist = cv2.distanceTransform((~self.edges).astype(np.uint8), cv2.DIST_L2, 3)
        self.W, self.H = w, h


def synthetic_edges(scene):
    """Organ boundaries: where the organ index changes, restricted to vegetation."""
    o = scene.obj.astype(np.int32)
    e = np.zeros_like(o, bool)
    e[:, 1:] |= o[:, 1:] != o[:, :-1]
    e[1:, :] |= o[1:, :] != o[:-1, :]
    return e & scene.vegetation


def ncc(a, b, mask):
    a = a[mask].astype(np.float64)
    b = b[mask].astype(np.float64)
    if a.size < 50:
        return 0.0
    a -= a.mean()
    b -= b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d > 0 else 0.0


def local_score(cues, scene, window, tau_px=None, weights=(1.0, 1.0, 1.0)):
    """Score a scene against the real cues inside a window (boolean mask), higher is better.

    `tau_px` is the distance at which an edge counts as missed; default 3 px at the raster
    scale (12 real pixels, about 1 cm at the canopy). The edge term is the fraction of edge
    pixels, real and synthetic, that have a counterpart within tau: a capped-mean chamfer
    distance saturated near 1 for any plausible plant, because dense foliage always has an
    edge within a leaf-width of any pixel.
    """
    m = window & cues.valid
    if tau_px is None:
        tau_px = max(2.0, 3.0 * cues.W / 648.0)
    syn_veg = scene.vegetation
    inter = (syn_veg & cues.veg & m).sum()
    union = ((syn_veg | cues.veg) & m).sum()
    iou = float(inter / union) if union else 0.0
    se = synthetic_edges(scene) & m
    re = cues.edges & m
    if se.sum() > 20 and re.sum() > 20:
        hit_s = float((cues.edge_dist[se] <= tau_px).mean())
        syn_dist = cv2.distanceTransform((~se).astype(np.uint8), cv2.DIST_L2, 3)
        hit_r = float((syn_dist[re] <= tau_px).mean())
        edge = 0.5 * (hit_s + hit_r)
    else:
        edge = 0.0
    # shading: luminance against n.z on pixels both call vegetation
    both = m & syn_veg & cues.veg
    shade = ncc(cues.L, scene.normal[..., 2], both)
    w = weights
    total = (w[0] * iou + w[1] * edge + w[2] * max(shade, 0.0)) / sum(w)
    return dict(total=total, iou=iou, edge=edge, shade=shade)


def window_around(px, py, radius_px, W, H):
    yy, xx = np.mgrid[0:H, 0:W]
    return (xx - px) ** 2 + (yy - py) ** 2 <= radius_px ** 2


# ---------------------------------------------------------------- layout ---

def row_layout(target, ov, spacing_m=None, offset_m=0.0, margin_px=60, age=40.0, rng_seed=0):
    """Sites along each detected row at a fixed in-row spacing, inside the valid frame. `spacing_m` defaults to the
    in-row spacing of the species the overrides name (twin.species; cowpea 0.15 m)."""
    if spacing_m is None:
        from . import species as S
        spacing_m = S.get(S.of_overrides(ov))["inrow_spacing_m"]
    H, W = target.veg.shape
    valid_rows = np.where(target.valid.any(1))[0]
    y_top, y_bot = valid_rows.min() + margin_px, valid_rows.max() - margin_px
    rng = np.random.RandomState(rng_seed)
    sites = []
    for col in target.rows:
        x_m, y_hi = R.ground_xy(col, y_top, camera_height_m=ov["camera.height"])
        _, y_lo = R.ground_xy(col, y_bot, camera_height_m=ov["camera.height"])
        y = y_lo + offset_m
        while y <= y_hi:
            sites.append(dict(x=float(x_m), y=float(y), yaw_deg=float(rng.uniform(0, 360)), age=float(age), seed=int(rng.randint(1, 2**31 - 1)), present=True))
            y += spacing_m
    return sites


def site_pixel(s, ov, scale):
    """Image position of a site's base at raster scale."""
    fx = R.FX * scale
    px = 0.5 * R.WIDTH * scale + fx * s["x"] / ov["camera.height"]
    py = 0.5 * R.HEIGHT * scale - fx * s["y"] / ov["camera.height"]
    return px, py


# ------------------------------------------------------------------- fit ---

def fit_closed(target, ov, sites, workdir, n_seeds=8, yaws=(0, 90, 180, 270), ages=(-6, 0, 6), sweeps=2,
               radius_m=0.25, workers=6, log=print, extra=None):
    """Coordinate descent over sites with the structural local score.

    `extra` (optional): per-site list of (age, seed, yaw_deg) candidates added to the random ones.
    A validation on a pseudo-real target uses it to put the true plant in the pool, so the question
    "does the score prefer the truth when offered it?" can be answered at all.
    """
    sc = F.px_scale(ov)
    cues = RealCues(target, sc)
    W, H = cues.W, cues.H
    radius_px = radius_m * R.FX * sc / ov["camera.height"]
    cand_dir = os.path.join(workdir, "cand")
    os.makedirs(cand_dir, exist_ok=True)
    rng = np.random.RandomState(1)
    active = [s for s in sites if s.get("present", True)]
    history = []
    for sweep in range(sweeps):
        t0 = time.time()
        order = rng.permutation(len(active))
        for k in order:
            s = active[k]
            rest = scene_without(ov, active, int(k), cand_dir, f"rest_{k}")
            px, py = site_pixel(s, ov, sc)
            window = window_around(px, py, radius_px, W, H)
            # candidates: current plant, plus seeds x yaws x ages; also the empty site
            jobs = [(s["age"], s["seed"], s["x"], s["y"], s["yaw_deg"], cand_dir, f"cur_{k}")]
            for seed in rng.randint(1, 2**31 - 1, size=n_seeds):
                for yaw in yaws:
                    for da in ages:
                        jobs.append((max(4.0, s["age"] + da), int(seed), s["x"], s["y"], float(yaw), cand_dir, f"c{k}_{seed}_{int(yaw)}_{int(da)}"))
            n_random = len(jobs)
            if extra is not None and extra[k]:
                for j, (age, seed, yaw) in enumerate(extra[k]):
                    jobs.append((float(age), int(seed), s["x"], s["y"], float(yaw), cand_dir, f"x{k}_{j}"))
            res = F.candidates(ov, jobs, workers)
            best = (local_score(cues, rest, window)["total"], None)  # empty site
            best_terms = None
            scored = []
            for job, (veg, x0, y0) in zip(jobs, res):
                cand = TR.Maps(cand_dir, job[6])
                sc_ = local_score(cues, rest.composite(cand, k + 1), window)
                scored.append(sc_["total"])
                if sc_["total"] > best[0]:
                    best, best_terms = (sc_["total"], job), sc_
            if extra is not None and extra[k]:
                order = np.argsort(-np.array(scored))
                ranks = [int(np.where(order == n_random + j)[0][0]) + 1 for j in range(len(extra[k]))]
                log(f"    site {k:2d}: extra candidates scored {[round(scored[n_random + j], 3) for j in range(len(extra[k]))]} rank {ranks} of {len(jobs)}; best random {max(scored[:n_random]):.3f}")
                s["extra_rank"] = ranks
            if best[1] is None:
                s["present"] = False
                log(f"  sweep {sweep} site {k:2d}: EMPTY is best ({best[0]:.3f})")
            else:
                age, seed, x, y, yaw = best[1][:5]
                s.update(age=age, seed=seed, yaw_deg=yaw, present=True, score=best[0])
                log(f"  sweep {sweep} site {k:2d}: score {best[0]:.3f} (iou {best_terms['iou']:.2f} edge {best_terms['edge']:.2f} shade {best_terms['shade']:.2f}) age {age:.0f} yaw {yaw:.0f} seed {seed}")
        full = scene_without(ov, [s for s in active if s.get("present", True)], None, cand_dir, "full")
        tot = local_score(cues, full, cues.valid)
        history.append(tot)
        log(f"sweep {sweep}: whole-frame score {tot['total']:.3f} (iou {tot['iou']:.3f} edge {tot['edge']:.3f} shade {tot['shade']:.3f}) in {time.time() - t0:.0f} s")
    kept = [s for s in active if s.get("present", True)]
    layout = os.path.join(workdir, "layout.txt")
    TR.write_layout(layout, kept)
    json.dump(dict(sites=kept, history=history, overrides=ov, target=target.path), open(os.path.join(workdir, "fit.json"), "w"), indent=1)
    return kept, layout, history
