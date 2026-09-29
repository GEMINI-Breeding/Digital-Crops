"""Leaf scale against structure radius, measured by rendering.

The rasterized pass cannot do this. Its 22-second turnaround depends on procedural leaves; with the
scanned OBJ meshes the render uses it takes ~30 minutes, seven times slower than ray tracing the
same scene, and calibrating on procedural leaves and rendering with OBJ is the mismatch that broke
the section 12 cover calibration. So this renders, develops and tiles exactly as the dataset does,
and measures the pattern spectrum on tiles the same way the real set is measured -- no calibration
constant in the path at all.

Reports cover and box count alongside, because widening leaf scale once already fixed structure
radius and overshot canopy cover.
"""
import glob, json, os, subprocess, sys
import numpy as np, cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real import camera_pipeline as cp
from syn2real.tile import tile_frame
from syn2real.geometry import granulometry
from syn2real.geom_io import HALF_RADII, REPORTED_RADII
from syn2real.leafcolour import summarise as leafcolour

BASE = json.load(open("audit/phase5_confirm.json"))["results"]["18"]["overrides"]
WIDTH = float(BASE["leaf.prototype_scale_max"]) - float(BASE["leaf.prototype_scale_min"])
MINS = [0.094, 0.125, 0.155]
SEEDS = (9200, 9201, 9202)
REAL = dict(mean_r=38.7, peak_r=8, cover_p50=0.947, boxes=7.57, a_spread=8.73, L_spread=15.78)


def spectrum(tiles):
    fs = sorted(glob.glob(os.path.join(tiles, "images", "*.jpeg")))
    acc = np.zeros(len(HALF_RADII))
    for f in fs:
        g = cv2.cvtColor(cv2.imread(f), cv2.COLOR_BGR2GRAY)
        g = cv2.resize(g, (g.shape[1] // 2, g.shape[0] // 2), interpolation=cv2.INTER_AREA)
        acc += granulometry(g, HALF_RADII)
    spec = acc / max(len(fs), 1)
    radii = np.asarray(REPORTED_RADII, float)
    return float(radii[int(np.argmax(spec))]), float((radii * spec).sum() / spec.sum())


print(f"{'leaf scale':>14} {'peak_r':>7} {'mean_r':>7} {'cover p50':>10} {'boxes/tile':>11} "
      f"{'a* spread':>10} {'L* spread':>10}", flush=True)
rows = []
for lo in MINS:
    hi = lo + WIDTH
    tag = f"{lo:.3f}"
    raw, dev, tiles = f"ls_raw_{tag}", f"ls_dev_{tag}", f"ls_tiles_{tag}"
    for d in (raw, dev, tiles):
        os.system(f"rm -rf {d}")
    ov = dict(BASE)
    ov["leaf.prototype_scale_min"] = f"{lo:.4f}"
    ov["leaf.prototype_scale_max"] = f"{hi:.4f}"
    flat = [x for kv in ov.items() for x in kv]
    for seed in SEEDS:
        r = subprocess.run(["./SyntheticAutotuning", "render", "../config/baseline.cfg", str(seed),
                            "camera.samples", "50", "output.folder", f"../{raw}/"] + flat,
                           capture_output=True, text=True, cwd="build-gpu")
        if r.returncode != 0:
            raise SystemExit(f"render failed at {lo}: {(r.stderr.strip().splitlines() or ['?'])[-1]}")
    subprocess.run(["env/bin/python", "scripts/develop.py", raw, "--out", dev,
                    "--target-L", str(cp.REAL_FOLIAGE_L)], check=True, capture_output=True)
    written = []
    for i, img in enumerate(sorted(glob.glob(os.path.join(dev, "*_RGB.jpeg")))):
        stem = os.path.basename(img).replace("camA_", "").replace("_RGB.jpeg", "")
        label = os.path.join(raw, stem + "_bbox.txt")
        if not os.path.exists(label):
            continue
        written += tile_frame(img, label, tiles, n_tiles=15, seed=6000 + i,
                              rover_mask_path=os.path.join(raw, "camA_" + stem + "_rover.txt"),
                              ground_mask_path=os.path.join(raw, "camA_" + stem + "_ground.txt"))
    cov = np.array([t[1] for t in written]); box = np.array([t[2] for t in written])
    peak, mean_r = spectrum(tiles)
    lc = leafcolour(tiles)
    rows.append(dict(scale_min=lo, scale_max=hi, peak_r=peak, mean_r=mean_r,
                     cover_p50=float(np.median(cov)), cover_p5=float(np.percentile(cov, 5)),
                     boxes=float(box.mean()), a_spread=lc["a_spread"],
                     L_spread=lc["L_spread_within_tile"], tiles=len(written)))
    print(f"{lo:.3f}-{hi:.3f} {peak:7.0f} {mean_r:7.2f} {np.median(cov):10.3f} "
          f"{box.mean():11.2f} {lc['a_spread']:10.2f} {lc['L_spread_within_tile']:10.2f}", flush=True)
    for d in (raw, dev, tiles):
        os.system(f"rm -rf {d}")

json.dump(dict(real=REAL, rows=rows), open("audit/leaf_scale_render.json", "w"), indent=1)
print(f"{'REAL':>14} {REAL['peak_r']:7d} {REAL['mean_r']:7.2f} {REAL['cover_p50']:10.3f} "
      f"{REAL['boxes']:11.2f} {REAL['a_spread']:10.2f} {REAL['L_spread']:10.2f}")
best = min(rows, key=lambda r: abs(r["mean_r"] - REAL["mean_r"]))
print(f"\nclosest structure radius: leaf scale {best['scale_min']:.3f}-{best['scale_max']:.3f} "
      f"-> mean_r {best['mean_r']:.2f} (real {REAL['mean_r']}), cover {best['cover_p50']:.3f} "
      f"(real {REAL['cover_p50']})")
print("LEAF SCALE RENDER COMPLETE")
