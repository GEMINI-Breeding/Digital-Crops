"""Does the geometry work help or hurt detection?

Section 17 improved four distribution statistics -- flower density 15.5 -> 7.39 against a real 7.57,
canopy cover and its sparse tail, and the leaf angle distribution -- at the cost of leaving trial 18,
the only configuration whose detection performance has ever been measured. Section 15 found that
distribution fidelity does not predict mAP (rank correlation -0.07 across eight configurations), so
the trade cannot be assumed in either direction.

BOTH configurations are re-measured here, not just the new one. Trial 18's confirmed 0.4577 was
obtained before today's colour work -- the scene-fitted colour matrix, the develop gain of 648.7, the
nitrogen model and its floor -- so every training image has changed since, and comparing a new number
against that old one would confound geometry with colour. A fresh scene seed forces both through the
current pipeline rather than returning the cached result.
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real.map_objective import evaluate

SCENE_SEED0 = 8100          # unused by either cached entry, so both configs are evaluated afresh
TRAIN_SEEDS = (3, 4, 5)
FRAMES = 6

trial18 = json.load(open("audit/phase5_confirm.json"))["results"]["18"]["overrides"]
best = json.load(open("audit/best_config.json"))["overrides"]

print(f"scenes {SCENE_SEED0}+, training seeds {TRAIN_SEEDS}, {FRAMES} frames per configuration")
print("both configurations evaluated under the CURRENT colour pipeline\n", flush=True)

results = {}
for name, ov in (("trial 18 (geometry as measured in s15)", trial18),
                 ("best config (s17 geometry)", best)):
    mean, se, detail = evaluate(ov, frames=FRAMES, train_seeds=TRAIN_SEEDS, scene_seed0=SCENE_SEED0)
    if not (mean == mean):     # NaN
        raise SystemExit(f"{name} unevaluable: {detail.get('reason')}")
    results[name] = dict(mAP50=mean, se=se, boxes=detail["boxes"], tiles=detail["tiles"],
                         runs=detail["runs"])
    print(f"  {name:42s} mAP50 {mean:.4f} +-{se:.4f}   {detail['boxes']} boxes, "
          f"{detail['tiles']} tiles", flush=True)

json.dump(dict(scene_seed0=SCENE_SEED0, train_seeds=list(TRAIN_SEEDS), results=results),
          open("audit/map_best_vs_trial18.json", "w"), indent=1)

a = results["trial 18 (geometry as measured in s15)"]
b = results["best config (s17 geometry)"]
diff = b["mAP50"] - a["mAP50"]
sed = (a["se"] ** 2 + b["se"] ** 2) ** 0.5
print(f"\nbest - trial18: {diff:+.4f} +- {sed:.4f}  = {diff/sed:+.1f} SE")
print(f"for reference, trial 18 measured 0.4577 +-0.0059 under the PREVIOUS colour pipeline")
print("MAP COMPARISON COMPLETE")
