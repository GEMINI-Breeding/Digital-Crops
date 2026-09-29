"""Stage 1 optimiser: generator shape parameters against one sparse frame.

Optuna TPE over twin.stage1.SPACE, objective = mean best per-plant silhouette IoU with fixed
seeds (see twin/stage1.py). The library defaults are the first trial so every later one is
measured against the configuration the sparse fit used. Resumable: the study lives in a sqlite
file under the work directory.

usage: twin_stage1_opt.py <date> [plot] [--trials 80] [--plants 8] [--seeds 6] [--yaws 8] [--workers N] [--tag name] [--scale 0.5]
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
ap.add_argument("date"); ap.add_argument("plot", nargs="?", default="Plot286-MAGIC083")
ap.add_argument("--trials", type=int, default=80); ap.add_argument("--plants", type=int, default=8)
ap.add_argument("--seeds", type=int, default=6); ap.add_argument("--yaws", type=int, default=8)
ap.add_argument("--workers", type=int, default=int(os.environ.get("TWIN_WORKERS", "6")))
ap.add_argument("--tag", default=None); ap.add_argument("--scale", type=float, default=0.5)
a = ap.parse_args()

fs = R.frames(a.date, a.plot)
path = fs[len(fs) // 2]
work = os.path.join(TR.PROJECT, "twin_work", a.tag or f"{a.date}_{a.plot}_stage1opt")
os.makedirs(work, exist_ok=True)
logf = open(os.path.join(work, "opt.log"), "a")
def say(*x):
    s = " ".join(str(v) for v in x); print(s, flush=True); logf.write(s + "\n"); logf.flush()

target = F.Target(path, work)
base = dict(F.BASE); base["raster.scale"] = a.scale
obj = S1.Stage1Objective(target, base, n_plants=a.plants, n_seeds=a.seeds, n_yaws=a.yaws, workers=a.workers, workdir=work, log=say)
say(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} {path}: {len(obj.plants)} plants (areas {[int(p['area_px']) for p in obj.plants]}), {len(obj.seeds)} seeds x {len(obj.yaws)} yaws, binary {TR.BINARY}")

optuna.logging.set_verbosity(optuna.logging.WARNING)
study = optuna.create_study(direction="maximize", study_name="stage1", storage=f"sqlite:///{work}/stage1.db",
                            load_if_exists=True, sampler=optuna.samplers.TPESampler(seed=0, multivariate=True, n_startup_trials=12))
if len(study.trials) == 0:
    study.enqueue_trial(S1.DEFAULTS)

def objective(trial):
    x = {k: trial.suggest_float(k, lo, hi) for k, (lo, hi) in S1.SPACE.items()}
    ov = S1.to_overrides(x)
    mean, best, ages = obj(ov, tag=f"t{trial.number}")
    trial.set_user_attr("per_plant", best); trial.set_user_attr("ages", ages); trial.set_user_attr("overrides", ov)
    say(f"trial {trial.number}: {mean:.4f}  " + " ".join(f"{k.split('.')[-1]}={v:.3g}" for k, v in ov.items() if isinstance(v, float)))
    return mean

t0 = time.time()
study.optimize(objective, n_trials=a.trials)
best = study.best_trial
say(f"BEST trial {best.number}: {best.value:.4f} in {time.time() - t0:.0f} s")
say(json.dumps(best.user_attrs.get("overrides", {})))
json.dump(dict(best_value=best.value, best_overrides=best.user_attrs.get("overrides", {}), per_plant=best.user_attrs.get("per_plant"),
               trials=[dict(number=t.number, value=t.value, overrides=t.user_attrs.get("overrides"), per_plant=t.user_attrs.get("per_plant")) for t in study.trials if t.value is not None]),
          open(os.path.join(work, "stage1_opt.json"), "w"), indent=1)
