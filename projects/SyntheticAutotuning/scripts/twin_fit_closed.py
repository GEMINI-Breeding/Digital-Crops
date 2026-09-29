"""Fit a closed-canopy frame with the structural local score.
usage: twin_fit_closed.py <date|image path> [plot] [--spacing 0.15] [--age 40] [--seeds 8] [--sweeps 2] [--scale 0.25] [--workers N] [--tag name]
"""
import os, sys, json, time, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import twin.real as R, twin.fit as F, twin.canopy as C

ap = argparse.ArgumentParser()
ap.add_argument("date"); ap.add_argument("plot", nargs="?", default="Plot286-MAGIC083")
ap.add_argument("--spacing", type=float, default=0.15); ap.add_argument("--age", type=float, default=40.0)
ap.add_argument("--seeds", type=int, default=8); ap.add_argument("--sweeps", type=int, default=2)
ap.add_argument("--scale", type=float, default=0.25); ap.add_argument("--workers", type=int, default=int(os.environ.get("TWIN_WORKERS", "6")))
ap.add_argument("--tag", default=None); ap.add_argument("--layout", default=None, help="initial layout file instead of the row prior")
a = ap.parse_args()
if os.path.exists(a.date):
    path = a.date
else:
    fs = R.frames(a.date, a.plot); path = fs[len(fs) // 2]
tag = a.tag or f"{a.date}_{a.plot}_closed"
work = os.path.join(F.TR.PROJECT, "twin_work", tag); os.makedirs(work, exist_ok=True)
log = open(os.path.join(work, "fit.log"), "a")
def say(*x):
    s = " ".join(str(v) for v in x); print(s, flush=True); log.write(s + "\n"); log.flush()
say(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} frame {path}")
target = F.Target(path, work)
ov = dict(F.BASE); ov["raster.scale"] = a.scale
if a.layout:
    sites = [dict(s, present=True) for s in F.TR.read_sites(a.layout)] if open(a.layout).readline().startswith("SITE") else None
    if sites is None:
        sites = []
        for line in open(a.layout):
            t = line.split()
            if len(t) >= 5 and not line.startswith("#"):
                sites.append(dict(x=float(t[0]), y=float(t[1]), yaw_deg=float(t[2]), age=float(t[3]), seed=int(t[4]), present=True))
else:
    sites = C.row_layout(target, ov, spacing_m=a.spacing, age=a.age)
say(f"target cover {target.cover:.3f} rows {target.rows}; {len(sites)} initial sites")
t0 = time.time()
kept, layout, hist = C.fit_closed(target, ov, sites, work, n_seeds=a.seeds, sweeps=a.sweeps, workers=a.workers, log=say)
full = C.scene_without(ov, kept, None, work, "final")
F.overlay(target, F.TR.Maps(work, "final"), os.path.join(work, "overlay.jpg"))
say(f"done: {len(kept)} plants kept, {time.time() - t0:.0f} s; layout {layout}")
