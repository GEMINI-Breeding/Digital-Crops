"""Does the model need its plants young, or is the fit using age as a size knob?

Every fit so far has chosen each plant's age freely, and it chooses ages far below the stand's real one: about 20 days
for 33-day-old plants. Leaf number rides on age, so any leaf-production parameter we fit is partly compensating for
that. This holds each plant at the stand age implied by the assumed 2023-05-31 planting and evaluates the same fitted
positions and yaws, at the same generator parameters, against the real frame. Cover near real at true age would mean the
model's growth rate is sound and the fit was compensating; cover far above it would mean the model really does grow too
fast, and phyllochron and branching should be fitted with ages pinned rather than free.

usage: twin_trueage_probe.py [--suffix _yawfix] [--overrides twin_work/size_refit_ov.json] [--planting 2023-05-31]
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np  # noqa: E402

import twin.fit as F  # noqa: E402
import twin.raster as TR  # noqa: E402

FRAMES = ["2023-06-20_Plot286-MAGIC083", "2023-06-20_Plot201-MAGIC262", "2023-06-27_Plot286-MAGIC083",
          "2023-06-27_Plot298-MAGIC226", "2023-07-03_Plot286-MAGIC083"]

ap = argparse.ArgumentParser()
ap.add_argument("--suffix", default="_yawfix")
ap.add_argument("--overrides", default=os.path.join(TR.PROJECT, "twin_work", "size_refit_ov.json"))
ap.add_argument("--planting", default="2023-05-31")
a = ap.parse_args()

planting = datetime.date.fromisoformat(a.planting)
ov = json.load(open(a.overrides))
print(f"planting {planting}, overrides phyllochron {ov.get('canopy.phyllochron')}, "
      f"bud break {ov.get('canopy.bud_break_probability', 'library default')}\n")
print(f"{'frame':26} {'stand age':>9} {'fitted age':>11} | {'cover real':>10} {'fitted':>8} {'true age':>9} | {'IoU fitted':>11} {'IoU true':>9}")
for fr in FRAMES:
    work = os.path.join(TR.PROJECT, "twin_work", fr + a.suffix)
    fit = json.load(open(os.path.join(work, "fit.json")))
    target = F.Target(fit["target"], work)
    stand_age = (datetime.date.fromisoformat(fr[:10]) - planting).days
    fitted = [dict(s) for s in fit["sites"]]
    at_true = []
    for s in fitted:
        t = dict(s)
        t["age"] = float(stand_age)
        at_true.append(t)
    probe_layout = os.path.join(work, "layout_trueage.txt")
    TR.write_layout(probe_layout, at_true)
    fitted_scene = [json.loads(l.split("scene: ")[1]) for l in open(os.path.join(work, "fit.log")) if l.startswith("scene: ")][-1]
    true_scene, _ = F.evaluate_layout(target, ov, probe_layout, work, base="trueage")
    print(f"{fr:26} {stand_age:9d} {np.median([s['age'] for s in fitted]):11.1f} | {true_scene['cover_real']:10.3f} "
          f"{fitted_scene['cover_syn']:8.3f} {true_scene['cover_syn']:9.3f} | {fitted_scene['iou']:11.3f} {true_scene['iou']:9.3f}")
