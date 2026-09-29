"""Phase 5: joint optimisation of scene and architecture parameters.

Why joint rather than one parameter at a time. The Morris screen returned sigma comparable to or
larger than mu* for nearly every parameter, which is its way of reporting interactions: the effect
of one parameter depends on where the others sit. This project has already paid for that twice --
lowering germination fixed canopy cover and halved flower count, and widening leaf scale fixed
structure radius and overshot cover. Coordinate descent cannot see either coupling.

Two objectives are supported behind one interface, because it is not yet known whether any cheap
metric predicts detection performance:

  "proxy"  -- the asymmetric objective over statistics the rasterized pass produces in ~22 s.
              Thousands of evaluations are affordable. Only trustworthy if proxy validation shows
              it tracks mAP; the five dataset versions to date cannot establish that, since they
              improved monotonically together and so correlate with almost anything.

  "map"    -- measured detection mAP against held-out real imagery, ~20 min per evaluation
              including render, tile and train. Slow enough that only a few dozen configurations
              are reachable, but it is the quantity actually being optimised rather than a stand-in.

The interface is deliberately identical so the objective can be swapped without restructuring the
search, and so a proxy-driven search can be re-scored against mAP afterwards.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Callable

import numpy as np

from .screen import PROBLEM, to_overrides

#: Search space, taken from the screening problem so the two stay consistent by construction.
SPACE = {name: tuple(bounds) for name, bounds in zip(PROBLEM["names"], PROBLEM["bounds"])}

#: Statistics available from the rasterized pass, with the real values to match.
#:
#: Every value recomputed from the full 263-tile real set (previously several were a 40-tile draw):
#: cover 0.947->0.927, and the granulometry entries are new. `boxes` is per FRAME and its derivation
#: from the real per-tile 7.5703 is not recorded anywhere -- treat it as provisional. `nn` is
#: measured over a whole frame on the synthetic side and within 640 px tiles on the real one, so the
#: two are not on the same scale; it ranks synthetic settings and should not be matched to target.
#: granulo_peak_r is deliberately absent. The rasterized peak is constant at 8 px across the whole
#: leaf-scale range, so scoring it would contribute an exact zero to every configuration's error and
#: dilute the statistics that do discriminate. It is measured and reported, not optimised.
REAL_GEOM = dict(cover=0.927, boxes=24.2, size_p50=33.002, size_p95=48.799, logasp=0.0408,
                 nn=69.453, granulo_mean_r=38.7)


def suggest(trial):
    """One configuration from an Optuna trial, in the same override form the screen uses."""
    row = []
    for name, (lo, hi) in SPACE.items():
        row.append(trial.suggest_float(name, lo, hi))
    return to_overrides(np.array(row))


def run_geom(overrides, seed, workdir="opt_work", binary="./SyntheticAutotuning",
             config="../config/baseline.cfg", granulometry=False):
    """Rasterized evaluation of one configuration. Returns the geometric statistics, or None.

    `granulometry` additionally renders the RGB pass and measures the leaf/canopy pattern spectrum.
    It costs an extra rasterization, and its spectrum is Phong-shaded rather than ray-traced, so it
    tracks the rendered spectrum only up to a calibration -- see scripts/validate_granulometry.py.
    """
    from .geom_io import read_boxes, nn_spacing, granulometry_from_render, calibrated_mean_radius
    from .tile import REAL_MIN_BOX_PX

    tag = f"{workdir}/s{seed}"
    args = [binary, "geom", config, str(seed),
            "leaf.use_obj_mesh", "0", "geom.label_leaves", "1",
            "geom.write_rgb", "1" if granulometry else "0",
            "output.folder", f"../{tag}/"]
    for k, v in overrides.items():
        args += [k, v]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        # A failed run must not silently become a zero: an earlier screen lost 100 of 104 rows this
        # way and still produced a ranked table.
        return None
    cover = next((float(t.split("=")[1]) for t in r.stdout.split() if t.startswith("veg_cover=")), np.nan)
    runs = sorted(os.listdir(f"../{tag}")) if os.path.isdir(f"../{tag}") else []
    if not runs:
        return None
    run_dir = os.path.join(f"../{tag}", runs[-1])
    b = read_boxes(run_dir)
    b = b[np.isin(b["name"], ("flower_open", "flower_closed"))]
    b = b[b["size"] >= REAL_MIN_BOX_PX]
    spectrum_stats = {}
    if granulometry:
        # Read before the directory is removed; a missing rendering raises rather than returning
        # a zero spectrum, because the difference is a misconfigured run, not a flat canopy.
        peak_r, mean_r, _ = granulometry_from_render(run_dir)
        # Reported on the ray-traced scale, so it is comparable with the real target in REAL_GEOM.
        # The raw rasterized value is kept alongside it for diagnosis.
        spectrum_stats = dict(granulo_peak_r=peak_r,
                              granulo_mean_r=calibrated_mean_radius(mean_r),
                              granulo_mean_r_raw=mean_r)
    os.system(f"rm -rf ../{tag}")
    if len(b) < 2:
        return None
    return dict(cover=cover, boxes=float(len(b)),
                size_p50=float(np.median(b["size"])), size_p95=float(np.percentile(b["size"], 95)),
                logasp=float(np.median(np.log(b["aspect"]))), nn=nn_spacing(b),
                **spectrum_stats)


def proxy_objective(overrides, seeds=(901, 902, 903), granulometry=False):
    """Mean relative distance from the real geometric statistics, averaged over seeds.

    Seeds matter: a single scene is a draw from the model, and germination alone moves cover by
    0.13 between draws at low stand density.

    `granulometry` includes the leaf/canopy pattern spectrum, which needs the extra RGB rasterization.
    Without it the two spectrum entries of REAL_GEOM are simply not scored -- they are the only
    statistics in that table the geom pass cannot produce for free.
    """
    per_seed = []
    for s in seeds:
        stats = run_geom(overrides, s, granulometry=granulometry)
        if stats is None:
            return float("inf")
        missing = [k for k in REAL_GEOM if k not in stats and not k.startswith("granulo_")]
        if missing:
            raise KeyError(f"run_geom did not return {missing}; REAL_GEOM and run_geom disagree")
        per_seed.append([abs(stats[k] - v) / max(abs(v), 1e-6)
                         for k, v in REAL_GEOM.items() if k in stats])
    return float(np.mean(per_seed))


def optimize(objective: Callable[[dict], float], n_trials=200, study_name="phase5",
             storage=None, seed=0):
    """Run the search. TPE handles the mixed continuous space and needs no gradient.

    Storage is a sqlite path when given, so a run that outlives its allocation can be resumed
    rather than restarted -- a proxy search is thousands of evaluations and will not fit one job.
    """
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(
        direction="minimize", study_name=study_name,
        storage=f"sqlite:///{storage}" if storage else None,
        load_if_exists=bool(storage),
        sampler=optuna.samplers.TPESampler(seed=seed, multivariate=True, group=True),
    )

    def _wrapped(trial):
        return objective(suggest(trial))

    study.optimize(_wrapped, n_trials=n_trials, show_progress_bar=False)
    return study


def report(study, top=10):
    lines = [f"{'rank':>4s} {'value':>9s}  parameters", "-" * 96]
    trials = [t for t in study.trials if t.value is not None and np.isfinite(t.value)]
    for rank, t in enumerate(sorted(trials, key=lambda t: t.value)[:top], 1):
        params = " ".join(f"{k.split('.')[-1]}={v:.3f}" for k, v in t.params.items())
        lines.append(f"{rank:4d} {t.value:9.4f}  {params}")
    lines.append(f"\n{len(trials)} completed of {len(study.trials)} trials")
    return "\n".join(lines)
