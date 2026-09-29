"""mAP per dataset for the size experiment, against the same held-out real split."""
import glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real.tier2 import split_real, build_dataset, sample, train_eval

N, SEEDS, EPOCHS = 96, (0, 1, 2), int(os.environ.get("TIER2_EPOCHS", "60"))
real_train, real_test = split_real("real")
res = {}
for d in sorted(glob.glob("synthetic_size*")):
    name = os.path.basename(d)
    runs = []
    for s in SEEDS:
        names = sample(d, N, seed=17)
        y = build_dataset(f"tier2_work/{name}_s{s}", [(d, names)], ("real", real_test))
        m = train_eval(y, f"{name}_s{s}", epochs=EPOCHS, seed=s)
        runs.append(m)
        print(f"  {name} seed={s}: mAP50={m['mAP50']:.4f}", flush=True)
    res[name] = runs
json.dump(res, open("audit/tier2_size.json", "w"), indent=1)
print("MAP COMPLETE")
