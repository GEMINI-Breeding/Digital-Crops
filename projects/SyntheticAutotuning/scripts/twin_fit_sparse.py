"""Fit one sparse-canopy T4 frame (default: Plot286-MAGIC083, 2023-06-20) on the raster proxy."""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import twin.real as R, twin.fit as F

import argparse
ap = argparse.ArgumentParser()
ap.add_argument("date", nargs="?", default="2023-06-20"); ap.add_argument("plot", nargs="?", default="Plot286-MAGIC083")
ap.add_argument("n_seeds", nargs="?", type=int, default=12)
ap.add_argument("--overrides", default=None, help="JSON file with generator overrides (e.g. a Stage-1 optimiser result: its best_overrides)")
ap.add_argument("--tag", default=None)
ap.add_argument("--emergence", default=None,
                help="emergence date (YYYY-MM-DD): every plant starts at (frame date - emergence) days instead of taking its age from its footprint")
ap.add_argument("--emergence-jitter", type=float, default=0.0,
                help="days stage 4 may move an individual plant from the stand age, so plants still differ in vigour")
a = ap.parse_args()
date, plot, n_seeds = a.date, a.plot, a.n_seeds
fs = R.frames(date, plot)
path = fs[len(fs) // 2]
work = os.path.join(F.TR.PROJECT, "twin_work", a.tag or f"{date}_{plot}")
os.makedirs(work, exist_ok=True)
log = open(os.path.join(work, "fit.log"), "a")
def say(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); log.write(s + "\n"); log.flush()
say(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} frame {path}")
target = F.Target(path, work)
ov = dict(F.BASE)
if a.overrides:
    extra = json.load(open(a.overrides))
    extra = extra.get("best_overrides", extra)
    ov.update(extra)
    say("overrides:", json.dumps(extra))
t0 = time.time()
pin_age = None
if a.emergence:
    import datetime
    pin_age = (datetime.date.fromisoformat(date) - datetime.date.fromisoformat(a.emergence)).days
    say(f"ages pinned at {pin_age} days (emergence {a.emergence}, jitter +/-{a.emergence_jitter:g} d)")
sites, layout = F.fit_sparse(target, ov, work, n_seeds=n_seeds, workers=int(os.environ.get("TWIN_WORKERS", "6")), log=say, pin_age=pin_age, pin_age_jitter=a.emergence_jitter)
res, maps = F.evaluate_layout(target, ov, layout, work)
say("scene:", json.dumps(res))
F.overlay(target, maps, os.path.join(work, "overlay.jpg"))
say(f"total {time.time() - t0:.0f} s; overlay at {work}/overlay.jpg")
