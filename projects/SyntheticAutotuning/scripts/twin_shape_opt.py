"""Leaf-shape Stage 1: the generator's silhouette, leaflet shape and posture parameters against leaf-level targets.

Optuna TPE over twin.stage1.SHAPE_SPACE. The objective for a parameter vector is the mean over the given frames of
twin.stage1.LeafShapeObjective: best per-plant silhouette IoU with fixed seeds, minus penalties on visible leaflet length and
width and on the thin-structure fraction against the real frame's targets (twin_work/leaflets/targets.json). Fitting two dates
of one plot keeps the shape from being tuned to one growth stage. Resumable (sqlite study in the work directory).

usage: twin_shape_opt.py [--frames F1 F2 ...] [--trials 250] [--plants 8] [--seeds 6] [--yaws 8] [--tag name]
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
import twin.stage1 as S1  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--frames", nargs="+", default=["2023-06-20_Plot286-MAGIC083", "2023-06-27_Plot286-MAGIC083"])
ap.add_argument("--trials", type=int, default=250)
ap.add_argument("--plants", type=int, default=8)
ap.add_argument("--seeds", type=int, default=6)
ap.add_argument("--yaws", type=int, default=8)
ap.add_argument("--tag", default="shape_opt")
a = ap.parse_args()
workers = int(os.environ.get("TWIN_WORKERS", "6"))

work = os.path.join(TR.PROJECT, "twin_work", a.tag)
os.makedirs(work, exist_ok=True)
logf = open(os.path.join(work, "opt.log"), "a")


def say(*x):
    s = " ".join(str(v) for v in x)
    print(s, flush=True)
    logf.write(s + "\n")
    logf.flush()


targets = json.load(open(os.path.join(TR.PROJECT, "twin_work", "leaflets", "targets.json")))
objectives = []
for fr in a.frames:
    fit = json.load(open(os.path.join(TR.PROJECT, "twin_work", fr + "_leaf", "fit.json")))
    target = F.Target(fit["target"], os.path.join(work, fr))
    base = dict(F.BASE)
    objectives.append((fr, S1.LeafShapeObjective(target, base, targets[fr], n_plants=a.plants, n_seeds=a.seeds, n_yaws=a.yaws, workers=workers,
                                                  workdir=os.path.join(work, fr), log=say)))
    say(f"{fr}: {len(objectives[-1][1].plants)} plants, target leaflet {targets[fr]['major']:.1f} x {targets[fr]['minor']:.1f} px, thin {targets[fr]['thin']:.3f}")
say(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} {len(a.frames)} frames, {a.seeds} seeds x {a.yaws} yaws, binary {TR.BINARY}")

optuna.logging.set_verbosity(optuna.logging.WARNING)
study = optuna.create_study(direction="maximize", study_name="shape", storage=f"sqlite:///{work}/shape.db", load_if_exists=True,
                            sampler=optuna.samplers.TPESampler(seed=0, multivariate=True, n_startup_trials=24))
if len(study.trials) == 0:
    for start in S1.SHAPE_STARTS:
        study.enqueue_trial(start)


def objective(trial):
    x = {k: trial.suggest_float(k, lo, hi) for k, (lo, hi) in S1.SHAPE_SPACE.items()}
    ov = S1.shape_overrides(x)
    scores, parts = [], {}
    for fr, obj in objectives:
        score, best, ages = obj(ov, tag=f"t{trial.number}")
        scores.append(score)
        parts[fr] = dict(score=score, per_plant=best, ages=ages, **obj.last)
    mean = float(np.mean(scores))
    trial.set_user_attr("overrides", ov)
    trial.set_user_attr("frames", parts)
    say(f"trial {trial.number}: {mean:.4f}  " + " ".join(f"{k.split('.')[-1]}={v:.3g}" for k, v in ov.items() if isinstance(v, float)))
    return mean


t0 = time.time()
study.optimize(objective, n_trials=max(0, a.trials - len([t for t in study.trials if t.value is not None])))
best = study.best_trial
say(f"BEST trial {best.number}: {best.value:.4f} in {time.time() - t0:.0f} s")
say(json.dumps(best.user_attrs.get("overrides", {})))
json.dump(dict(best_value=best.value, best_overrides=best.user_attrs.get("overrides", {}), best_frames=best.user_attrs.get("frames"),
               trials=[dict(number=t.number, value=t.value, overrides=t.user_attrs.get("overrides"), frames=t.user_attrs.get("frames")) for t in study.trials if t.value is not None]),
          open(os.path.join(work, "shape_opt.json"), "w"), indent=1)
