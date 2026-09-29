"""Is the leaf-nitrogen gradient visible to the camera, or hidden under the canopy?

The nitrogen model builds a wide chlorophyll gradient -- Cab 19.6 to 84 -- and the analytic pigment
study says a spread that size is worth about 8 a* units through this camera, close to the real 8.73.
The rendered images show none of it, and the visible population shifted PALER rather than wider.

The suspicion is occlusion: a nadir camera over a closed canopy sees the newest growth on top, which
is exactly the nitrogen-poor end, while the old dark leaves sit underneath. This compares the
distribution of leaf nitrogen over LEAVES (what the model built, from the DIAG line) against the
distribution over VISIBLE PIXELS (what the camera actually sees, from the per-pixel map).

If the visible distribution is much narrower and paler than the true one, occlusion is confirmed and
no pigment or nitrogen change will fix it -- the remedy would be structural.
"""
import glob, json, os, re, subprocess, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SEED = 5200
BASE = json.load(open("audit/phase5_confirm.json"))["results"]["18"]["overrides"]
SETTING = {"leaf.nitrogen_model": "1", "leaf.target_N_area": "4.2",
           "leaf.max_N_accumulation_rate": "0.140", "leaf.nitrogen_supply_gN": "8.0"}
RAW = "occl_raw"
CAB_PER_N = 100.0 * 0.50 * 0.40

os.system(f"rm -rf {RAW}")
ov = dict(BASE); ov.update(SETTING)
flat = [x for kv in ov.items() for x in kv]
r = subprocess.run(["./SyntheticAutotuning", "render", "../config/baseline.cfg", str(SEED),
                    "camera.samples", "50", "output.folder", f"../{RAW}/"] + flat,
                   capture_output=True, text=True, cwd="build-gpu")
if r.returncode != 0:
    raise SystemExit(f"render failed: {(r.stderr.strip().splitlines() or ['no stderr'])[-1]}")

diag = next((l for l in r.stdout.splitlines() if "DIAG leafN" in l), None)
if diag is None:
    raise SystemExit("no DIAG leafN line; the nitrogen model did not report")
print("over LEAVES (what the model built):")
print("  " + diag.strip())

maps = sorted(glob.glob(os.path.join(RAW, "*_leafN.txt")))
if not maps:
    raise SystemExit(f"no *_leafN.txt under {RAW}; the per-pixel nitrogen map was not written")
grid = np.loadtxt(maps[0])
visible = grid[np.isfinite(grid) & (grid > 0)]
if visible.size == 0:
    raise SystemExit("the nitrogen map contains no leaf pixels")

pct = lambda q: float(np.percentile(visible, q))
print(f"\nover VISIBLE PIXELS (what the camera sees), n={visible.size}:")
print(f"  N   p10 {pct(10):.2f}  p50 {pct(50):.2f}  p90 {pct(90):.2f}  mean {visible.mean():.2f}")
print(f"  Cab p10 {pct(10)*CAB_PER_N:.1f}  p50 {pct(50)*CAB_PER_N:.1f}  p90 {pct(90)*CAB_PER_N:.1f}"
      f"  spread {(pct(90)-pct(10))*CAB_PER_N:.1f}")

m = {k: float(v) for k, v in re.findall(r"(Cab_p\d+|N_p50)=([-\d.eE+]+)", diag)}
if "Cab_p10" in m and "Cab_p90" in m:
    leaf_spread = m["Cab_p90"] - m["Cab_p10"]
    vis_spread = (pct(90) - pct(10)) * CAB_PER_N
    print(f"\nCab spread over leaves   {leaf_spread:.1f}")
    print(f"Cab spread over pixels   {vis_spread:.1f}   ({vis_spread/max(leaf_spread,1e-6)*100:.0f}% retained)")
    print(f"Cab median over leaves   {m.get('Cab_p50', float('nan')):.1f}")
    print(f"Cab median over pixels   {pct(50)*CAB_PER_N:.1f}")

# Area-weighted age bias: what fraction of visible leaf pixels are below the median leaf's nitrogen?
if "N_p50" in m:
    below = float((visible < m["N_p50"]).mean())
    print(f"\nvisible pixels below the median LEAF's nitrogen: {below*100:.1f}%")
    print("  (50% means no bias; well above 50% means the camera sees mostly young, pale leaves)")

os.system(f"rm -rf {RAW}")
print("\nOCCLUSION TEST COMPLETE")
