"""Calibrate the nitrogen model in the geom pass, without rendering anything.

Leaf nitrogen and the chlorophyll it implies are computed by the plant model, before any ray
tracing. The whole per-leaf Cab distribution is therefore available from the 18-second rasterized
pass -- roughly twenty times cheaper than the render-develop-tile loop the first three calibration
attempts used, all of which measured colour three transformations downstream of the quantity they
were actually tuning.

The design point is set by what must NOT move. Real and synthetic canopies already agree on median
colour, so the median leaf must keep the chlorophyll the uniform path gave it (leaf.chlorophyll,
47.5); everything gained should be spread around that. Because the canopy's age distribution is
skewed young, the median leaf sits well below target -- at target 3.0 and rate 0.10 the median Cab
is 34, not 60 -- so target has to sit ABOVE the uniform value, not at it.

Rendered a* spread still has to be confirmed on the finalists: Cab spread is upstream of PROSPECT,
the camera and the colour matrix, and none of those is guaranteed to preserve it.
"""
import itertools, json, os, re, subprocess, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TARGETS = [2.6, 3.0, 3.4, 3.8, 4.2]
RATES = [0.10, 0.12, 0.14, 0.16, 0.20]
SEEDS = [5200, 5201]
UNIFORM_CAB = 47.5
OUT = "audit/geom_nitrogen_sweep.json"
BASE = json.load(open("audit/phase5_confirm.json"))["results"]["18"]["overrides"]

FIELDS = ("N_p50", "N_mean", "Cab_p10", "Cab_p25", "Cab_p50", "Cab_p75", "Cab_p90",
          "Cab_spread", "uniform_Cab")


def run_point(target, rate, seed):
    ov = dict(BASE)
    ov.update({"leaf.nitrogen_model": "1", "leaf.target_N_area": f"{target:.3f}",
               "leaf.max_N_accumulation_rate": f"{rate:.3f}",
               "leaf.nitrogen_supply_gN": "8.0"})
    args = ["./SyntheticAutotuning", "geom", "../config/baseline.cfg", str(seed),
            "leaf.use_obj_mesh", "0", "output.folder", "../gnsweep/"]
    for k, v in ov.items():
        args += [k, v]
    r = subprocess.run(args, capture_output=True, text=True, cwd="build-gpu")
    os.system("rm -rf gnsweep")
    if r.returncode != 0:
        raise SystemExit(f"geom failed at target {target} rate {rate} seed {seed}: "
                         f"{(r.stderr.strip().splitlines() or ['no stderr'])[-1]}")
    line = next((l for l in r.stdout.splitlines() if "DIAG leafN" in l), None)
    if line is None:
        raise SystemExit(f"no 'DIAG leafN' line at target {target} rate {rate}; "
                         "the nitrogen model did not report")
    out = {}
    for field in FIELDS:
        m = re.search(rf"\b{field}=([-\d.eE+]+)", line)
        if m is None:
            raise SystemExit(f"field {field} missing from: {line}")
        out[field] = float(m.group(1))
    return out


rows = []
print(f"{'target':>7} {'rate':>6} {'Cab p10':>8} {'Cab p50':>8} {'Cab p90':>8} "
      f"{'spread':>7} {'|p50-47.5|':>11}", flush=True)
for target, rate in itertools.product(TARGETS, RATES):
    per_seed = [run_point(target, rate, s) for s in SEEDS]
    row = dict(target_N=target, rate=rate)
    for field in FIELDS:
        row[field] = float(np.mean([p[field] for p in per_seed]))
    rows.append(row)
    print(f"{target:7.1f} {rate:6.2f} {row['Cab_p10']:8.1f} {row['Cab_p50']:8.1f} "
          f"{row['Cab_p90']:8.1f} {row['Cab_spread']:7.1f} "
          f"{abs(row['Cab_p50'] - UNIFORM_CAB):11.1f}", flush=True)

json.dump(dict(uniform_Cab=UNIFORM_CAB, seeds=SEEDS, rows=rows), open(OUT, "w"), indent=1)

# Finalists: median chlorophyll closest to the uniform value, then widest spread among those.
holding = [r for r in rows if abs(r["Cab_p50"] - UNIFORM_CAB) <= 4.0]
if not holding:
    best = min(rows, key=lambda r: abs(r["Cab_p50"] - UNIFORM_CAB))
    print(f"\nNo setting holds the median within 4 Cab of {UNIFORM_CAB}. Closest: "
          f"target {best['target_N']} rate {best['rate']} -> Cab p50 {best['Cab_p50']:.1f}.")
    print("The grid needs re-centring rather than a winner picking from it.")
else:
    holding.sort(key=lambda r: -r["Cab_spread"])
    print(f"\n=== hold median within 4 Cab of {UNIFORM_CAB}, widest spread first ===")
    for r in holding[:5]:
        print(f"  target {r['target_N']:.1f}  rate {r['rate']:.2f}   "
              f"Cab {r['Cab_p10']:.1f}-{r['Cab_p50']:.1f}-{r['Cab_p90']:.1f}  "
              f"spread {r['Cab_spread']:.1f}")
    print(f"\nrender these to check the a* spread reaches the real 8.73: "
          f"{[(r['target_N'], r['rate']) for r in holding[:3]]}")
print(f"\nwrote {OUT}")
print("GEOM NITROGEN SWEEP COMPLETE")
