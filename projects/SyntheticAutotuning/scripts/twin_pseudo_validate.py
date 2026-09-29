"""Closed-canopy validation on a pseudo-real target: a ray-traced render of a KNOWN layout.

The rendered JPEG supplies luminance and edges exactly as a real photo would; the vegetation
mask comes from the rasterizer's label map of the same layout (colour is not trusted here).
Every site starts from the true position and age but a random seed and yaw; the fit must
recover the true seeds. usage: twin_pseudo_validate.py <render.jpeg> <truth_layout.txt> [--seeds 8] [--sweeps 1] [--workers N] [--tag t]
"""
import argparse, json, os, sys, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import twin.fit as F, twin.raster as TR, twin.canopy as C, twin.real as R

ap = argparse.ArgumentParser()
ap.add_argument("image"); ap.add_argument("layout")
ap.add_argument("--seeds", type=int, default=8); ap.add_argument("--sweeps", type=int, default=1)
ap.add_argument("--scale", type=float, default=0.25); ap.add_argument("--workers", type=int, default=int(os.environ.get("TWIN_WORKERS", "6")))
ap.add_argument("--tag", default="pseudo_validate"); ap.add_argument("--sites", type=int, default=0, help="limit to the first N sites (0 = all)")
a = ap.parse_args()
work = os.path.join(TR.PROJECT, "twin_work", a.tag); os.makedirs(work, exist_ok=True)
log = open(os.path.join(work, "fit.log"), "a")
def say(*x):
    s = " ".join(str(v) for v in x); print(s, flush=True); log.write(s + "\n"); log.flush()
truth = []
for line in open(a.layout):
    t = line.split()
    if len(t) >= 5 and not line.startswith("#"):
        truth.append(dict(x=float(t[0]), y=float(t[1]), yaw_deg=float(t[2]), age=float(t[3]), seed=int(t[4]), present=True))
if a.sites:
    truth = truth[: a.sites]
ov = dict(F.BASE); ov["raster.scale"] = 1.0
o = dict(ov); o["canopy.layout_file"] = os.path.abspath(a.layout)
m = TR.run(o, seed=1, folder=work, base="truth_full")
veg = m.vegetation
rover = np.zeros_like(veg)
target = F.Target(a.image, work, undistort=False, veg_mask=veg, rover_mask=rover)
say(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} pseudo target {a.image}; {len(truth)} sites; cover {target.cover:.3f}")
ov["raster.scale"] = a.scale
rng = np.random.RandomState(7)
init = [dict(s, seed=int(rng.randint(1, 2**31 - 1)), yaw_deg=float(rng.uniform(0, 360))) for s in truth]
cues = C.RealCues(target, a.scale)
truth_scene = C.scene_without(ov, truth, None, work, "truth_scene")
init_scene = C.scene_without(ov, init, None, work, "init_scene")
say("whole-frame score: truth", json.dumps({k: round(v, 3) for k, v in C.local_score(cues, truth_scene, cues.valid).items()}),
    " random init", json.dumps({k: round(v, 3) for k, v in C.local_score(cues, init_scene, cues.valid).items()}))
t0 = time.time()
# The true plant (exact age, seed and yaw) plus the true plant turned by 90/180/270 degrees is
# offered at every site alongside the random candidates; the log reports where they rank.
extra = [[(t["age"], t["seed"], (t["yaw_deg"] + d) % 360) for d in (0, 90, 180, 270)] for t in truth]
kept, layout, hist = C.fit_closed(target, ov, init, work, n_seeds=a.seeds, sweeps=a.sweeps, workers=a.workers, log=say, extra=extra)
rec = sum(1 for s, t in zip(init, truth) if s.get("present", True) and s["seed"] == t["seed"])
exact = sum(1 for s, t in zip(init, truth) if s.get("present", True) and s["seed"] == t["seed"] and abs(((s["yaw_deg"] - t["yaw_deg"] + 180) % 360) - 180) < 1)
top1 = sum(1 for s in init if s.get("extra_rank") and s["extra_rank"][0] == 1)
say(f"true seed chosen at {rec}/{len(truth)} sites (exact yaw at {exact}); true plant ranked first at {top1}/{len(truth)} sites; {time.time() - t0:.0f} s")
