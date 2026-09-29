"""Phase 5: search scene and architecture parameters against measured detection mAP.

Not against a cheap objective. Across eight configurations drawn from the Morris design -- diverse
by construction rather than a sequential improvement series -- the asymmetric objective's rank
correlation with mAP is -0.07 (p 0.87), and distance-from-real predicts nothing either. So the
search optimises the quantity it cares about, at roughly twenty minutes per evaluation.

Seeded from cfg1 (0.401 mAP, the best measured configuration) rather than from the hand-tuned
versions, which it beats. The bounds are drawn in around it: at ~20 min per trial the budget is
tens of evaluations, not thousands, so the search cannot afford to explore the whole space and is
better used refining a region already known to be good.

flower.prototype_scale gets a deliberately wide range despite that. It is the parameter the size
sweep showed to matter most -- 0.030 scores 0.259 and 0.045 scores 0.400 -- and the mechanism is
that it regulates how many flowers clear the labelling threshold rather than how large they are.
"""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import optuna
from syn2real.map_objective import evaluate
from syn2real.screen import to_overrides, PROBLEM

optuna.logging.set_verbosity(optuna.logging.WARNING)
BASE = json.load(open("audit/validation_configs.json"))["cfg1"]["overrides"]

#: Narrowed around cfg1. Where cfg1 sits at a bound the range is opened on that side.
SPACE = {
    "canopy.germination_fraction_min":    (0.55, 0.95),
    "canopy.plant_spacing_y":             (0.11, 0.20),
    "canopy.age":                         (26, 40),
    "leaf.prototype_scale_min":           (0.09, 0.15),
    "leaf.prototype_scale_max":           (0.14, 0.20),
    "flower.prototype_scale":             (0.035, 0.060),
    "flower.closed_scale":                (1.0, 2.0),
    "flower.bud_break_prob_min":          (0.25, 0.50),
    "flower.inflorescence_pitch_max":     (60, 95),
    "flower.peduncle_length_max":         (0.25, 0.45),
    "phenology.time_to_flower_initiation": (10, 18),
    "phenology.time_to_flower_opening":   (2, 6),
}
N_TRIALS = int(os.environ.get("PHASE5_TRIALS", "30"))
STORAGE = os.path.abspath("audit/phase5.db")

def suggest(trial):
    row = [trial.suggest_float(n, *SPACE[n]) for n in PROBLEM["names"]]
    return to_overrides(np.array(row))

def objective(trial):
    ov = suggest(trial)
    mean, se, detail = evaluate(ov, frames=6, train_seeds=(0, 1, 2))
    if not np.isfinite(mean):
        print(f"  trial {trial.number}: UNEVALUABLE ({detail.get('reason')})", flush=True)
        raise optuna.TrialPruned()
    trial.set_user_attr("se", se); trial.set_user_attr("boxes", detail["boxes"])
    print(f"  trial {trial.number}: mAP50={mean:.4f} +-{se:.4f}  "
          f"{detail['boxes']} boxes  scale={ov['flower.prototype_scale']}", flush=True)
    return -mean

study = optuna.create_study(direction="minimize", study_name="phase5",
                            storage=f"sqlite:///{STORAGE}", load_if_exists=True,
                            sampler=optuna.samplers.TPESampler(seed=0, multivariate=True, group=True))
# Start from the best known configuration so the search never does worse than where it began.
if not study.trials:
    study.enqueue_trial({n: float(BASE[n]) for n in PROBLEM["names"]})
study.optimize(objective, n_trials=N_TRIALS)

done = [t for t in study.trials if t.value is not None]
print(f"\n=== {len(done)} evaluated, best first ===")
for t in sorted(done, key=lambda t: t.value)[:8]:
    print(f"  mAP {-t.value:.4f} +-{t.user_attrs.get('se',float('nan')):.4f}  "
          + " ".join(f"{k.split('.')[-1]}={v:.3f}" for k, v in t.params.items()))
print("\nreference: cfg1 0.4012, v18 0.3760, real-only ceiling 0.8793")
print("PHASE5 COMPLETE")
