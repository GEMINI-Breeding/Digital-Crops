"""cfg1 confirmation at 12 frames and 6 seeds, alongside v18 for a like-for-like comparison."""
import glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real.tier2 import split_real, build_dataset, sample, train_eval

SEEDS, EPOCHS = (0, 1, 2, 3, 4, 5), int(os.environ.get("TIER2_EPOCHS", "60"))
real_train, real_test = split_real("real")
res = {}
for d in ("synthetic_cfg1x", "synthetic_v18"):
    if not os.path.isdir(d):
        continue
    runs = []
    for s in SEEDS:
        names = sample(d, 120, seed=17)
        y = build_dataset(f"tier2_work/{d}_s{s}", [(d, names)], ("real", real_test))
        m = train_eval(y, f"{d}_s{s}", epochs=EPOCHS, seed=s)
        runs.append(m)
        print(f"  {d} seed={s}: mAP50={m['mAP50']:.4f}", flush=True)
    res[d] = runs
json.dump(res, open("audit/tier2_cfg1x.json", "w"), indent=1)
print("MAP COMPLETE")
