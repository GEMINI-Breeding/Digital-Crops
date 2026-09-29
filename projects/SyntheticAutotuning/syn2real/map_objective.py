"""Detection mAP as an optimisation objective: render, develop, tile, train, score.

The cheap objective is not usable. Measured across eight configurations drawn from the Morris
design -- diverse by construction rather than sequential -- the asymmetric objective's rank
correlation with mAP is -0.07 (p 0.87), and distance-from-real predicts nothing either (-0.02 for
object count, -0.24 for cover). So the search has to optimise the quantity it actually cares about.

That costs about twenty minutes per evaluation instead of twenty seconds, which changes the search
from thousands of trials to a few dozen and makes two things matter that did not before.

*Noise.* Repeat trainings of one dataset differ by 0.02-0.03 mAP. A sampler handed a noisy objective
will happily chase differences smaller than its own noise floor, so evaluations average several
seeds and the per-evaluation standard error is recorded alongside the value. Anything the search
"discovers" that is smaller than that is not a discovery.

*Caching.* Every evaluation is expensive and deterministic given its configuration, so results are
keyed by a hash of the overrides and reused. A resumed study re-evaluates nothing.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess

import numpy as np

from .camera_pipeline import REAL_FOLIAGE_L

CACHE = "audit/map_objective_cache.json"


DEFAULT_SCENE_SEED0 = 7000


def _key(overrides, frames, seeds, scene_seed0=DEFAULT_SCENE_SEED0):
    blob = {"o": dict(sorted(overrides.items())), "f": frames, "s": seeds}
    if scene_seed0 != DEFAULT_SCENE_SEED0:
        # The Phase 5 study was cached before scene_seed0 existed. Leaving the default out of the
        # key keeps those thirty entries valid instead of re-rendering twenty GPU-hours of scenes.
        blob["ss"] = scene_seed0
    return hashlib.sha1(json.dumps(blob, sort_keys=True).encode()).hexdigest()[:16]


def _load_cache():
    return json.load(open(CACHE)) if os.path.exists(CACHE) else {}


def _save_cache(cache):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    tmp = CACHE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(cache, fh, indent=1)
    os.replace(tmp, CACHE)          # atomic, so an interrupted run cannot corrupt the cache


def evaluate(overrides, frames=6, train_seeds=(0, 1, 2), samples=50, tag=None,
             workdir="opt", keep=False, scene_seed0=DEFAULT_SCENE_SEED0):
    """Full pipeline for one configuration. Returns (mean mAP50, standard error, detail).

    Returns (nan, nan, reason) rather than a number when the configuration cannot be evaluated --
    a failed render must not become a plausible score. An earlier screen lost 100 of 104 runs to
    silent failure and still produced a ranked table.

    ``scene_seed0`` selects which scenes are drawn, and the tiling seeds follow it. Moving it and
    ``train_seeds`` together gives an independent replicate of a configuration: the search selects
    the maximum over thirty noisy evaluations, so its winner is biased upward and its reported value
    is not an estimate of that configuration's performance until it is re-measured on fresh draws.
    """
    from .tier2 import split_real, build_dataset, sample as sample_tiles, train_eval
    from .tile import tile_frame

    tag = tag or _key(overrides, frames, tuple(train_seeds), scene_seed0)
    cache = _load_cache()
    if tag in cache and cache[tag].get("ok"):
        c = cache[tag]
        return c["mAP50"], c["se"], c

    fdir, ddir, tdir = f"{workdir}/frames_{tag}", f"{workdir}/dev_{tag}", f"{workdir}/tiles_{tag}"
    for d in (fdir, ddir, tdir):
        os.system(f"rm -rf {d}")

    ov = [x for kv in overrides.items() for x in kv]
    for i in range(frames):
        r = subprocess.run(["./SyntheticAutotuning", "render", "../config/baseline.cfg", str(scene_seed0 + i),
                            "camera.samples", str(samples), "output.folder", f"../{fdir}/"] + ov,
                           capture_output=True, text=True, cwd="build-gpu")
        if r.returncode != 0:
            detail = {"ok": False, "reason": (r.stderr.strip().splitlines() or ["render failed"])[-1]}
            cache[tag] = detail; _save_cache(cache)
            return float("nan"), float("nan"), detail

    # Exposure is calibrated PER CONFIGURATION rather than carried as a constant. Leaf angle,
    # canopy density and architecture all change how much light foliage intercepts, so a gain
    # bisected for one canopy mis-exposes another: the planophile canopy needed 374 where the
    # uniform one needed 649, and carrying the old value rendered foliage 13 L* too bright. Passing
    # --target-L instead of --gain makes every configuration land on the real foliage lightness, so
    # configurations differ in geometry and not in exposure.
    subprocess.run(["env/bin/python", "scripts/develop.py", fdir, "--out", ddir,
                    "--target-L", str(REAL_FOLIAGE_L)], check=True, capture_output=True)

    written = []
    import glob
    for i, img in enumerate(sorted(glob.glob(os.path.join(ddir, "*_RGB.jpeg")))):
        stem = os.path.basename(img).replace("camA_", "").replace("_RGB.jpeg", "")
        label = os.path.join(fdir, stem + "_bbox.txt")
        if not os.path.exists(label):
            continue
        written += tile_frame(img, label, tdir, n_tiles=15, seed=scene_seed0 - 2000 + i,
                              rover_mask_path=os.path.join(fdir, "camA_" + stem + "_rover.txt"),
                              ground_mask_path=os.path.join(fdir, "camA_" + stem + "_ground.txt"))
    n_boxes = int(sum(t[2] for t in written))
    if len(written) < 40 or n_boxes < 30:
        detail = {"ok": False, "reason": f"degenerate dataset: {len(written)} tiles, {n_boxes} boxes"}
        cache[tag] = detail; _save_cache(cache)
        return float("nan"), float("nan"), detail

    _, real_test = split_real("real")
    vals = []
    for s in train_seeds:
        names = sample_tiles(tdir, 120, seed=17)
        y = build_dataset(f"tier2_work/opt_{tag}_s{s}", [(tdir, names)], ("real", real_test))
        vals.append(train_eval(y, f"opt_{tag}_s{s}", epochs=60, seed=s)["mAP50"])
    mean = float(np.mean(vals))
    se = float(np.std(vals, ddof=1) / np.sqrt(len(vals))) if len(vals) > 1 else float("nan")
    detail = {"ok": True, "mAP50": mean, "se": se, "runs": vals, "tiles": len(written),
              "boxes": n_boxes, "overrides": overrides, "scene_seed0": scene_seed0,
              "train_seeds": list(train_seeds)}
    cache[tag] = detail; _save_cache(cache)
    if not keep:
        for d in (fdir, ddir, tdir):
            os.system(f"rm -rf {d}")
    return mean, se, detail


def objective(overrides, **kw):
    """Minimisation form for the optimiser: negative mAP, +inf when unevaluable."""
    mean, _, _ = evaluate(overrides, **kw)
    return float("inf") if not np.isfinite(mean) else -mean
