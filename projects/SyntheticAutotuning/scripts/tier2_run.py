"""Run the Tier-2 validation matrix and print a table of mAP against held-out real imagery."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real.tier2 import split_real, build_dataset, sample, train_eval

REAL = "real"
N_CONTROL = 120          # smallest synthetic set; every controlled condition uses this many
# Seed count is a real constraint here, not a formality. The baseline's three-seed spread was
# +-0.069 mAP50, so resolving a difference between conditions needed it to exceed ~0.08. Five seeds
# cuts the standard error by about a third.
SEEDS = tuple(range(int(os.environ.get("TIER2_SEEDS", "3"))))
EPOCHS = int(os.environ.get("TIER2_EPOCHS", "60"))
DATA_SEED = int(os.environ.get("TIER2_DATA_SEED", "17"))

real_train, real_test = split_real(REAL)
test_spec = (REAL, real_test)

conditions = []
for name, root in (("baseline", "synthetic"),
                   ("v_final", "synthetic_final"),
                   ("v17", "synthetic_v17"),
                   ("v18", "synthetic_v18"),
                   ("v21", "synthetic_v21")):
    if os.path.isdir(os.path.join(root, "images")):
        conditions.append((name, root, N_CONTROL, SEEDS))
# References, one seed each: the full baseline shows what 10x the data buys, real-only is the ceiling.
if os.path.isdir("synthetic/images"):
    conditions.append(("baseline_full", "synthetic", None, (0,)))
conditions.append(("real_only", REAL, None, (0,)))

results = {}
for name, root, n, seeds in conditions:
    runs = []
    for seed in seeds:
        # The tile subset is drawn with a FIXED seed, so the training seed varies only the training
        # run. Previously the subset moved with it, and the baseline -- 120 drawn from 1,307 -- got
        # a different sample each time: its SD was 0.080 against 0.013-0.026 for the conditions
        # whose tile count equals their dataset size. That inflated its error bar threefold and made
        # the conditions incomparable, since some were measuring subset variation and some were not.
        names = real_train if root == REAL else sample(root, n, seed=DATA_SEED)
        yaml_path = build_dataset(f"tier2_work/{name}_s{seed}", [(root, names)], test_spec)
        m = train_eval(yaml_path, f"{name}_s{seed}", epochs=EPOCHS, seed=seed)
        m["n_train"] = len(names)
        runs.append(m)
        print(f"  {name} seed={seed} n={len(names)}: mAP50={m['mAP50']:.4f} mAP50-95={m['mAP50-95']:.4f}", flush=True)
    results[name] = runs

print(f"\n{'condition':16s} {'n_train':>8s} {'mAP50':>16s} {'mAP50-95':>16s}")
print("-" * 60)
for name, runs in results.items():
    a = [r["mAP50"] for r in runs]
    b = [r["mAP50-95"] for r in runs]
    spread = lambda v: f"{sum(v)/len(v):.4f}" + (f" +-{(max(v)-min(v))/2:.4f}" if len(v) > 1 else "        ")
    print(f"{name:16s} {runs[0]['n_train']:8d} {spread(a):>16s} {spread(b):>16s}")
json.dump(results, open("audit/tier2.json", "w"), indent=2)
print("\nTIER2 DONE")
