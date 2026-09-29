"""Identifiability of the plant-model parameters from one nadir frame: simulation-based check.

A synthetic target is built from KNOWN parameters theta* (positions and ages of a real fitted
layout, fresh seeds, so it is a different realisation of the same model), rasterized at full
resolution, and its vegetation mask is handed to the Stage-1 optimiser exactly as a real frame's
mask would be. Recovery is then measured per parameter: how far the best trial and the top
trials sit from theta*, in units of the search range. A parameter the top trials scatter across
its whole range is not identified by this observable at this growth stage, whatever the real
fits say; a parameter they concentrate on is.

usage: twin_identifiability.py <layout_of_a_real_fit> [--truth defaults|best|random] [--trials 120] [--tag t] [--workers N]
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np  # noqa: E402
import optuna  # noqa: E402

import twin.fit as F  # noqa: E402
import twin.raster as TR  # noqa: E402
import twin.real as R  # noqa: E402
import twin.stage1 as S1  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("layout"); ap.add_argument("--truth", default="best", help="defaults | best (optimiser winner) | random (a draw from SPACE)")
ap.add_argument("--best-json", default=os.path.join(TR.PROJECT, "twin_work", "2023-06-20_Plot286-MAGIC083_stage1opt", "stage1_opt.json"))
ap.add_argument("--trials", type=int, default=120); ap.add_argument("--plants", type=int, default=8)
ap.add_argument("--seeds", type=int, default=6); ap.add_argument("--yaws", type=int, default=8)
ap.add_argument("--workers", type=int, default=int(os.environ.get("TWIN_WORKERS", "6")))
ap.add_argument("--tag", default=None); ap.add_argument("--scale", type=float, default=0.5); ap.add_argument("--truth-seed", type=int, default=99)
a = ap.parse_args()

work = os.path.join(TR.PROJECT, "twin_work", a.tag or f"ident_{a.truth}")
os.makedirs(work, exist_ok=True)
logf = open(os.path.join(work, "ident.log"), "a")
def say(*x):
    s = " ".join(str(v) for v in x); print(s, flush=True); logf.write(s + "\n"); logf.flush()

# --- theta* ------------------------------------------------------------------
rng = np.random.RandomState(a.truth_seed)
if a.truth == "defaults":
    x_true = dict(S1.DEFAULTS)
elif a.truth == "best":
    best = json.load(open(a.best_json))["best_overrides"]
    x_true = {k: (best[k] if k in best else best.get(k.replace("_width", "_max"), 0) - best.get(k.replace("_width", "_min"), 0)) for k in S1.SPACE}
    x_true["leaf.prototype_scale_width"] = best["leaf.prototype_scale_max"] - best["leaf.prototype_scale_min"]
    x_true["leaf.petiole_length_width"] = best["leaf.petiole_length_max"] - best["leaf.petiole_length_min"]
    x_true["leaf.petiole_pitch_width"] = best["leaf.petiole_pitch_max"] - best["leaf.petiole_pitch_min"]
else:
    x_true = {k: float(rng.uniform(lo, hi)) for k, (lo, hi) in S1.SPACE.items()}
ov_true = S1.to_overrides(x_true)
say(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} truth={a.truth}: " + json.dumps(ov_true))

# --- synthetic target: real layout's positions and ages, fresh seeds, theta* ---------------
sites = []
for line in open(a.layout):
    t = line.split()
    if len(t) >= 5 and not line.startswith("#"):
        sites.append(dict(x=float(t[0]), y=float(t[1]), yaw_deg=float(rng.uniform(0, 360)), age=float(t[3]), seed=int(rng.randint(1, 2**31 - 1))))
truth_layout = os.path.join(work, "truth_layout.txt")
TR.write_layout(truth_layout, sites)
ov = dict(F.BASE); ov.update(ov_true); ov["raster.scale"] = 1.0; ov["canopy.layout_file"] = truth_layout
m = TR.run(ov, seed=1, folder=work, base="truth_full")
veg = m.vegetation
# The Target needs an image for its plumbing; the real frame the layout came from serves, but
# every measurement below is taken from the synthetic mask, never from that image.
fit_json = os.path.join(os.path.dirname(os.path.abspath(a.layout)), "fit.json")
img = json.load(open(fit_json))["target"] if os.path.exists(fit_json) else R.frames("2023-06-20")[10]
target = F.Target(img, work, undistort=True, veg_mask=veg, rover_mask=np.zeros_like(veg))
# The plants are known here, so the row splitter is bypassed: per-plant masks come from the truth
# raster's site map (it merged 16 synthetic plants into 8 blobs when left to itself).
site_full = m.full("site")
target.plant_labels = site_full.astype(np.int32)
truth_plants = []
for k in range(len(sites)):
    ys, xs = np.nonzero(site_full == k + 1)
    if len(xs) < 3000:
        continue
    truth_plants.append(dict(label=k + 1, x=float(xs.mean()), y=float(ys.mean()), area_px=float(len(xs)), component=k + 1,
                             bbox=(int(xs.min()), int(ys.min()), int(np.ptp(xs) + 1), int(np.ptp(ys) + 1))))
target.plants = lambda **kw: truth_plants
say(f"synthetic target: {len(sites)} plants, cover {target.cover:.3f}, {len(truth_plants)} plants with >= 3000 px from the truth site map")

# --- optimiser, same as on a real frame -------------------------------------
base = dict(F.BASE); base["raster.scale"] = a.scale
obj = S1.Stage1Objective(target, base, n_plants=a.plants, n_seeds=a.seeds, n_yaws=a.yaws, workers=a.workers, workdir=work, log=say)
optuna.logging.set_verbosity(optuna.logging.WARNING)
study = optuna.create_study(direction="maximize", study_name="ident", storage=f"sqlite:///{work}/ident.db", load_if_exists=True,
                            sampler=optuna.samplers.TPESampler(seed=0, multivariate=True, n_startup_trials=12))
if len(study.trials) == 0:
    study.enqueue_trial(S1.DEFAULTS)
    study.enqueue_trial(x_true)  # the truth itself, so its objective value is on record
def objective(trial):
    x = {k: trial.suggest_float(k, lo, hi) for k, (lo, hi) in S1.SPACE.items()}
    mean, best_, ages = obj(S1.to_overrides(x), tag=f"t{trial.number}")
    trial.set_user_attr("x", x); trial.set_user_attr("per_plant", best_)
    say(f"trial {trial.number}: {mean:.4f}")
    return mean
t0 = time.time()
study.optimize(objective, n_trials=a.trials)

# --- recovery ----------------------------------------------------------------
done = [t for t in study.trials if t.value is not None]
done.sort(key=lambda t: -t.value)
top = done[: max(5, len(done) // 10)]
say(f"finished {len(done)} trials in {time.time() - t0:.0f} s; objective at truth (trial 1) {done and [t.value for t in study.trials if t.number == 1][0]:.4f}, best {done[0].value:.4f} (trial {done[0].number})")
rows = []
for k, (lo, hi) in S1.SPACE.items():
    span = hi - lo
    vals = np.array([t.user_attrs["x"][k] for t in top])
    err_best = (done[0].user_attrs["x"][k] - x_true[k]) / span
    rows.append(dict(param=k, truth=x_true[k], best=done[0].user_attrs["x"][k], err_best_frac=float(err_best),
                     top_median=float(np.median(vals)), top_spread_frac=float((np.percentile(vals, 90) - np.percentile(vals, 10)) / span),
                     top_bias_frac=float((np.median(vals) - x_true[k]) / span)))
    say(f"  {k:30s} truth {x_true[k]:8.4g}  best {done[0].user_attrs['x'][k]:8.4g} (err {err_best:+.2f} of range)  top-{len(top)} median {np.median(vals):8.4g} spread {rows[-1]['top_spread_frac']:.2f} bias {rows[-1]['top_bias_frac']:+.2f}")
json.dump(dict(truth=a.truth, x_true=x_true, ov_true=ov_true, best_value=done[0].value, rows=rows,
               trials=[dict(number=t.number, value=t.value, x=t.user_attrs["x"]) for t in done]),
          open(os.path.join(work, "identifiability.json"), "w"), indent=1)
say("identified (top-10% spread < 0.35 of range and |bias| < 0.15): " + ", ".join(r["param"] for r in rows if r["top_spread_frac"] < 0.35 and abs(r["top_bias_frac"]) < 0.15))
