"""Calibrate the nitrogen model against the measured leaf-colour spread.

Two parameters set the shape. `target_N_area` fixes where mature leaves land, and so the dark end
of the distribution; `max_N_accumulation_rate` caps how fast a new leaf fills, and so how far the
young ones lag behind -- the spread. They are swept together because the median colour must NOT
move: the real and synthetic canopies already agree on mean colour, and widening the distribution
while shifting it would trade one error for another.

Target, measured on 120 real tiles: a* p10-p90 spread 8.73 with a median of -22.42, and the deficit
is at the dark end -- real p10 -27.54 against the uniform canopy's -22.99, while the two pale ends
agree to 0.03. The uniform single-spectrum canopy this replaces sits at spread 4.14.

The window statistic is a MEAN. An earlier version took medians, and since OpenCV returns uint8 Lab
the result quantised to 1 a* unit -- two configurations whose renders demonstrably differed both
read "spread 6.00, median -20", which is not a measurement.
"""
import itertools, json, os, subprocess, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real import camera_pipeline as cp
from syn2real.leafcolour import summarise, REAL
from syn2real.tile import tile_frame
import glob

# A leaf's nitrogen is min(target, rate * days_alive), drawn from a shared per-plant pool. The first
# two grids swept target and rate while the POOL was the binding constraint -- measured supply_ratio
# 0.34, so no leaf reached target and neither parameter did anything. Supply is now sized to be
# non-limiting (config leaf.nitrogen_supply_gN 8.0) and only the two shape parameters are swept.
#
# Spread is widest when the oldest leaves just reach target: below that everything is rate-limited
# and the canopy is uniformly pale, above it everything saturates at target and is uniformly dark.
# That optimum is rate ~ target / 30 days, so the rates bracket 0.10-0.14 for these targets.
TARGETS = [3.0, 3.6, 4.2]
RATES = [0.10, 0.14, 0.20]
SEED = 5200
GAIN = cp.DEVELOP_GAIN
BASE = json.load(open("audit/phase5_confirm.json"))["results"]["18"]["overrides"]
OUT = "audit/nitrogen_calibration.json"


def render_and_measure(extra, tag):
    raw, dev, tiles = f"ncal_raw_{tag}", f"ncal_dev_{tag}", f"ncal_tiles_{tag}"
    for d in (raw, dev, tiles):
        os.system(f"rm -rf {d}")
    ov = dict(BASE); ov.update(extra)
    flat = [x for kv in ov.items() for x in kv]
    r = subprocess.run(["./SyntheticAutotuning", "render", "../config/baseline.cfg", str(SEED),
                        "camera.samples", "50", "output.folder", f"../{raw}/"] + flat,
                       capture_output=True, text=True, cwd="build-gpu")
    if r.returncode != 0:
        raise SystemExit(f"render failed for {tag}: {(r.stderr.strip().splitlines() or ['no stderr'])[-1]}")
    subprocess.run(["env/bin/python", "scripts/develop.py", raw, "--out", dev, "--target-L", str(cp.REAL_FOLIAGE_L)],
                   check=True, capture_output=True)
    for i, img in enumerate(sorted(glob.glob(os.path.join(dev, "*_RGB.jpeg")))):
        stem = os.path.basename(img).replace("camA_", "").replace("_RGB.jpeg", "")
        label = os.path.join(raw, stem + "_bbox.txt")
        if not os.path.exists(label):
            continue
        tile_frame(img, label, tiles, n_tiles=15, seed=SEED + i,
                   rover_mask_path=os.path.join(raw, "camA_" + stem + "_rover.txt"),
                   ground_mask_path=os.path.join(raw, "camA_" + stem + "_ground.txt"))
    stats = summarise(tiles)
    for d in (raw, dev, tiles):
        os.system(f"rm -rf {d}")
    return stats


rows = []
print(f"target: a* spread {REAL['a_spread']:.1f}, median {REAL['a_p50']:.1f}\n", flush=True)
off = render_and_measure({"leaf.nitrogen_model": "0"}, "off")
print(f"  nitrogen OFF                 spread {off['a_spread']:5.2f}  median {off['a_p50']:6.2f}  "
      f"p10 {off['a_p10']:6.2f}  L spread {off['L_spread_within_tile']:5.2f}", flush=True)
rows.append(dict(target_N=None, rate=None, **off))

for target, rate in itertools.product(TARGETS, RATES):
    extra = {"leaf.nitrogen_model": "1", "leaf.target_N_area": f"{target:.3f}",
             "leaf.max_N_accumulation_rate": f"{rate:.3f}",
             "leaf.nitrogen_supply_gN": "8.0"}
    st = render_and_measure(extra, f"t{target:.1f}_r{rate:.2f}")
    rows.append(dict(target_N=target, rate=rate, **st))
    print(f"  target {target:.1f}  rate {rate:.2f}      spread {st['a_spread']:5.2f}  "
          f"median {st['a_p50']:6.2f}  p10 {st['a_p10']:6.2f}  "
          f"L spread {st['L_spread_within_tile']:5.2f}", flush=True)

json.dump(dict(real=REAL, rows=rows), open(OUT, "w"), indent=1)

on = [r for r in rows if r["target_N"] is not None]
def cost(r):
    return abs(r["a_spread"] - REAL["a_spread"]) + abs(r["a_p50"] - REAL["a_p50"])
best = min(on, key=cost)
print(f"\nclosest to real: target_N_area {best['target_N']}  max_N_accumulation_rate {best['rate']}")
print(f"  spread {best['a_spread']:.2f} (real {REAL['a_spread']:.2f})   "
      f"median {best['a_p50']:.2f} (real {REAL['a_p50']:.2f})")
print(f"  nitrogen off was spread {off['a_spread']:.2f}, median {off['a_p50']:.2f}")
print(f"\nwrote {OUT}")
print("NITROGEN CALIBRATION COMPLETE")
