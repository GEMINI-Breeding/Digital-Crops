"""Render the geom-sweep finalists and check the chlorophyll spread survives to the image.

The geom pass can show that leaf chlorophyll spans 19.6-84 ug/cm2, but not that the canopy looks
any different: Cab sits upstream of PROSPECT, the ray tracer, the colour matrix and the tone curve.
Chlorophyll absorption also saturates -- past roughly 60 ug/cm2 visible reflectance barely moves --
so a wide Cab spread can collapse into a narrow a* spread.

The three finalists hold an identical median Cab (47.6, matching the uniform path's 47.5) and differ
only in spread: 48.4, 56.4, 64.4. If rendered a* spread rises across them, chlorophyll still has
purchase at the top end. If it plateaus, the dark end has to come from something other than Cab.
"""
import glob, json, os, subprocess, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real import camera_pipeline as cp
from syn2real.leafcolour import summarise, REAL
from syn2real.tile import tile_frame

FINALISTS = [(3.4, 0.14), (3.8, 0.14), (4.2, 0.14)]
SEEDS = [5200, 5201]
GAIN = cp.DEVELOP_GAIN
BASE = json.load(open("audit/phase5_confirm.json"))["results"]["18"]["overrides"]
OUT = "audit/nitrogen_finalists.json"


def render_and_measure(extra, tag):
    raw, dev, tiles = f"nfin_raw_{tag}", f"nfin_dev_{tag}", f"nfin_tiles_{tag}"
    for d in (raw, dev, tiles):
        os.system(f"rm -rf {d}")
    ov = dict(BASE); ov.update(extra)
    flat = [x for kv in ov.items() for x in kv]
    for seed in SEEDS:
        r = subprocess.run(["./SyntheticAutotuning", "render", "../config/baseline.cfg", str(seed),
                            "camera.samples", "50", "output.folder", f"../{raw}/"] + flat,
                           capture_output=True, text=True, cwd="build-gpu")
        if r.returncode != 0:
            raise SystemExit(f"render failed for {tag}: "
                             f"{(r.stderr.strip().splitlines() or ['no stderr'])[-1]}")
    subprocess.run(["env/bin/python", "scripts/develop.py", raw, "--out", dev, "--target-L", str(cp.REAL_FOLIAGE_L)],
                   check=True, capture_output=True)
    for i, img in enumerate(sorted(glob.glob(os.path.join(dev, "*_RGB.jpeg")))):
        stem = os.path.basename(img).replace("camA_", "").replace("_RGB.jpeg", "")
        label = os.path.join(raw, stem + "_bbox.txt")
        if not os.path.exists(label):
            continue
        tile_frame(img, label, tiles, n_tiles=15, seed=5000 + i,
                   rover_mask_path=os.path.join(raw, "camA_" + stem + "_rover.txt"),
                   ground_mask_path=os.path.join(raw, "camA_" + stem + "_ground.txt"))
    stats = summarise(tiles)
    for d in (raw, dev, tiles):
        os.system(f"rm -rf {d}")
    return stats


rows = []
print(f"real: a* spread {REAL['a_spread']:.2f}  median {REAL['a_p50']:.2f}  "
      f"p10 {REAL['a_p10']:.2f}  L spread {REAL['L_spread_within_tile']:.2f}\n", flush=True)
off = render_and_measure({"leaf.nitrogen_model": "0"}, "off")
print(f"  nitrogen OFF                spread {off['a_spread']:5.2f}  median {off['a_p50']:6.2f}  "
      f"p10 {off['a_p10']:6.2f}  L spread {off['L_spread_within_tile']:5.2f}", flush=True)
rows.append(dict(target_N=None, rate=None, cab_spread=0.0, **off))

CAB_SPREAD = {(3.4, 0.14): 48.4, (3.8, 0.14): 56.4, (4.2, 0.14): 64.4}
for target, rate in FINALISTS:
    st = render_and_measure({"leaf.nitrogen_model": "1", "leaf.target_N_area": f"{target:.3f}",
                             "leaf.max_N_accumulation_rate": f"{rate:.3f}",
                             "leaf.nitrogen_supply_gN": "8.0"}, f"t{target:.1f}")
    rows.append(dict(target_N=target, rate=rate, cab_spread=CAB_SPREAD[(target, rate)], **st))
    print(f"  target {target:.1f} rate {rate:.2f} (Cab spread {CAB_SPREAD[(target, rate)]:.1f})  "
          f"spread {st['a_spread']:5.2f}  median {st['a_p50']:6.2f}  p10 {st['a_p10']:6.2f}  "
          f"L spread {st['L_spread_within_tile']:5.2f}", flush=True)

json.dump(dict(real=REAL, rows=rows), open(OUT, "w"), indent=1)

on = [r for r in rows if r["target_N"] is not None]
cab = [r["cab_spread"] for r in on]
astar = [r["a_spread"] for r in on]
gain = (astar[-1] - astar[0]) / max(cab[-1] - cab[0], 1e-6)
print(f"\na* spread across the three: " + " -> ".join(f"{v:.2f}" for v in astar))
# Do NOT read a flat response as pigment saturation. scripts/pigment_axes.py measured the pure
# optics through this exact camera and colour matrix: at fixed lightness Cab correlates -0.83 with
# a*, and a Cab spread of this size is worth about 8 a* units on its own. So if the rendered spread
# does not move, the loss is between the pigment and the pixel -- occlusion, or a metric that
# averages across leaves -- not the pigment running out of effect.
print(f"  per unit of Cab spread: {gain:+.4f}  "
      f"({'responding' if gain > 0.01 else 'NO RESPONSE - loss is downstream of the pigment, see scripts/occlusion_test.py'})")
best = min(on, key=lambda r: abs(r["a_spread"] - REAL["a_spread"]) + abs(r["a_p50"] - REAL["a_p50"]))
print(f"\nclosest to real: target {best['target_N']} rate {best['rate']}  "
      f"spread {best['a_spread']:.2f} (real {REAL['a_spread']:.2f})  "
      f"median {best['a_p50']:.2f} (real {REAL['a_p50']:.2f})")
print(f"nitrogen off was spread {off['a_spread']:.2f}, median {off['a_p50']:.2f}")
print(f"\nwrote {OUT}")
print("NITROGEN FINALISTS COMPLETE")
