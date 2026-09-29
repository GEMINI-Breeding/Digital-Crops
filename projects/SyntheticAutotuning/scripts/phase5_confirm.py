"""Independent replicate of the Phase 5 winners.

The search reports the maximum over thirty noisy evaluations, and the maximum of noisy draws is
biased upward -- the winner's curse. Trials 23 and 28 scored 0.462 +-0.034 and 0.452 +-0.015 on
three training seeds each; with per-evaluation noise of that size, selecting the best of thirty can
manufacture a gap of several hundredths from configurations that are merely typical.

So the top configurations are re-measured on draws the search never saw: different scenes
(scene_seed0 8000 rather than 7000, which also moves the tiling seeds) and different training seeds
(3,4,5 rather than 0,1,2). Trial 0 -- cfg1, the search's starting point -- is re-measured under the
same fresh conditions as the reference, and trial 18, the best of the first twenty-one trials, tests
whether the final nine trials genuinely reached a better region.

A confirmed result looks like the ordering surviving with a gap larger than the fresh standard
errors. If the four collapse together, the search found nothing and its apparent 0.08 gain was
selection noise.
"""
import json, os, sys, sqlite3
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real.map_objective import evaluate
from syn2real.screen import to_overrides, PROBLEM

STORAGE = os.path.abspath("audit/phase5.db")
OUT = "audit/phase5_confirm.json"
TRIALS = [0, 18, 23, 28]
SCENE_SEED0 = 8000
TRAIN_SEEDS = (3, 4, 5)


def trial_params(numbers):
    con = sqlite3.connect(f"file:{STORAGE}?mode=ro", uri=True)
    cur = con.cursor()
    cur.execute("select trial_id, number from trials")
    tid2num = dict(cur.fetchall())
    cur.execute("select trial_id, param_name, param_value from trial_params")
    params = {}
    for tid, name, value in cur.fetchall():
        params.setdefault(tid2num[tid], {})[name] = value
    cur.execute("""select t.number, v.value from trials t
                   join trial_values v on v.trial_id = t.trial_id where t.state='COMPLETE'""")
    search_map = {n: -v for n, v in cur.fetchall()}
    missing = [n for n in numbers if n not in params]
    if missing:
        raise SystemExit(f"trials absent from {STORAGE}: {missing}")
    return params, search_map


params, search_map = trial_params(TRIALS)
results = {}
for number in TRIALS:
    row = np.array([params[number][name] for name in PROBLEM["names"]], dtype=float)
    overrides = to_overrides(row)
    mean, se, detail = evaluate(overrides, frames=6, train_seeds=TRAIN_SEEDS,
                                scene_seed0=SCENE_SEED0)
    if not np.isfinite(mean):
        print(f"  trial {number}: UNEVALUABLE ({detail.get('reason')})", flush=True)
        results[number] = {"ok": False, "reason": detail.get("reason")}
        continue
    results[number] = {"ok": True, "search_mAP50": search_map[number], "confirm_mAP50": mean,
                       "confirm_se": se, "runs": detail["runs"], "boxes": detail["boxes"],
                       "overrides": overrides}
    print(f"  trial {number}: search {search_map[number]:.4f} -> confirm {mean:.4f} +-{se:.4f} "
          f"({detail['boxes']} boxes)", flush=True)

with open(OUT, "w") as fh:
    json.dump({"scene_seed0": SCENE_SEED0, "train_seeds": list(TRAIN_SEEDS),
               "results": {str(k): v for k, v in results.items()}}, fh, indent=1)

print(f"\n=== confirmation, scenes {SCENE_SEED0}+, training seeds {TRAIN_SEEDS} ===")
print(f"{'trial':>6} {'search':>9} {'confirm':>9} {'se':>8} {'shift':>8}")
for number in TRIALS:
    r = results[number]
    if not r.get("ok"):
        print(f"{number:>6}  UNEVALUABLE: {r['reason']}")
        continue
    shift = r["confirm_mAP50"] - r["search_mAP50"]
    print(f"{number:>6} {r['search_mAP50']:9.4f} {r['confirm_mAP50']:9.4f} "
          f"{r['confirm_se']:8.4f} {shift:+8.4f}")
print("\nreference: v18 0.3760, real-only ceiling 0.8793")
print("PHASE5 CONFIRM COMPLETE")
