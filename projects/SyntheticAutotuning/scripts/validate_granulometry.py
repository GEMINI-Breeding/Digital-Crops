"""Does the rasterized pass's pattern spectrum track the ray-traced one?

The geom pass can now render an RGB image and measure a granulometric spectrum from it, which would
give leaf scale a direct observable inside the 22-second loop instead of only its indirect effect on
cover. But that image is Phong-shaded from a single fixed light with no leaf or soil spectra, while
the real spectrum -- and the synthetic spectrum it is compared against -- comes from a ray-traced,
colour-corrected, tone-mapped photograph. Bright structure in the two is not obviously the same
thing.

A metric that does not track is worse than no metric, so this sweeps leaf scale across its range and
measures the spectrum BOTH ways at each point. Usable in-loop means the two move together: a rank
correlation near 1 over the sweep. The absolute values need not agree -- an optimiser needs ordering,
not calibration -- but if they diverge or the rasterized curve is flat, the shortcut fails and leaf
size stays unobservable in the fast loop.
"""
import glob, json, os, subprocess, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real import camera_pipeline as cp
from syn2real.geom_io import granulometry_from_render, HALF_RADII, REPORTED_RADII
from syn2real.geometry import granulometry
from syn2real.tile import tile_frame

SCALES = [(0.08, 0.11), (0.10, 0.14), (0.12, 0.17), (0.14, 0.20), (0.16, 0.23)]
SEEDS = [4100, 4101]
GAIN = cp.DEVELOP_GAIN
OUT = "audit/granulo_validation.json"
BASE = json.load(open("audit/phase5_confirm.json"))["results"]["18"]["overrides"]


def overrides_for(lo, hi):
    ov = dict(BASE)
    ov["leaf.prototype_scale_min"] = f"{lo:.4f}"
    ov["leaf.prototype_scale_max"] = f"{hi:.4f}"
    return ov


def rasterized(ov, seed):
    tag = f"gval_geom_s{seed}"
    os.system(f"rm -rf {tag}")
    args = ["./SyntheticAutotuning", "geom", "../config/baseline.cfg", str(seed),
            "leaf.use_obj_mesh", "0", "geom.label_leaves", "1", "geom.write_rgb", "1",
            "output.folder", f"../{tag}/"]
    for k, v in ov.items():
        args += [k, v]
    r = subprocess.run(args, capture_output=True, text=True, cwd="build-gpu")
    if r.returncode != 0:
        raise SystemExit(f"geom failed: {(r.stderr.strip().splitlines() or ['no stderr'])[-1]}")
    runs = sorted(os.listdir(tag))
    peak, mean, _ = granulometry_from_render(os.path.join(tag, runs[-1]))
    os.system(f"rm -rf {tag}")
    return peak, mean


def raytraced(ov, seed):
    """Render, develop, tile, and measure the spectrum exactly as the real side is measured."""
    import cv2
    raw, dev, tiles = f"gval_raw_s{seed}", f"gval_dev_s{seed}", f"gval_tiles_s{seed}"
    for d in (raw, dev, tiles):
        os.system(f"rm -rf {d}")
    flat = [x for kv in ov.items() for x in kv]
    r = subprocess.run(["./SyntheticAutotuning", "render", "../config/baseline.cfg", str(seed),
                        "camera.samples", "50", "output.folder", f"../{raw}/"] + flat,
                       capture_output=True, text=True, cwd="build-gpu")
    if r.returncode != 0:
        raise SystemExit(f"render failed: {(r.stderr.strip().splitlines() or ['no stderr'])[-1]}")
    subprocess.run(["env/bin/python", "scripts/develop.py", raw, "--out", dev,
                    "--target-L", str(cp.REAL_FOLIAGE_L)], check=True, capture_output=True)
    for i, img in enumerate(sorted(glob.glob(os.path.join(dev, "*_RGB.jpeg")))):
        stem = os.path.basename(img).replace("camA_", "").replace("_RGB.jpeg", "")
        label = os.path.join(raw, stem + "_bbox.txt")
        if not os.path.exists(label):
            continue
        tile_frame(img, label, tiles, n_tiles=15, seed=seed + i,
                   rover_mask_path=os.path.join(raw, "camA_" + stem + "_rover.txt"),
                   ground_mask_path=os.path.join(raw, "camA_" + stem + "_ground.txt"))
    fs = sorted(glob.glob(os.path.join(tiles, "images", "*.jpeg")))
    if not fs:
        raise SystemExit(f"no tiles written for seed {seed}")
    acc = np.zeros(len(HALF_RADII))
    for f in fs:
        g = cv2.cvtColor(cv2.imread(f), cv2.COLOR_BGR2GRAY)
        g = cv2.resize(g, (g.shape[1] // 2, g.shape[0] // 2), interpolation=cv2.INTER_AREA)
        acc += granulometry(g, HALF_RADII)
    spec = acc / len(fs)
    radii = np.asarray(REPORTED_RADII, float)
    for d in (raw, dev, tiles):
        os.system(f"rm -rf {d}")
    return float(radii[int(np.argmax(spec))]), float((radii * spec).sum() / spec.sum()), len(fs)


rows = []
for lo, hi in SCALES:
    ov = overrides_for(lo, hi)
    rast = [rasterized(ov, s) for s in SEEDS]
    ray = [raytraced(ov, s) for s in SEEDS]
    row = dict(scale_min=lo, scale_max=hi,
               rast_peak=float(np.mean([p for p, _ in rast])),
               rast_mean=float(np.mean([m for _, m in rast])),
               ray_peak=float(np.mean([p for p, _, _ in ray])),
               ray_mean=float(np.mean([m for _, m, _ in ray])),
               ray_tiles=int(sum(n for _, _, n in ray)))
    rows.append(row)
    print(f"  leaf {lo:.2f}-{hi:.2f}:  rasterized mean_r {row['rast_mean']:6.2f} "
          f"(peak {row['rast_peak']:3.0f})   ray-traced mean_r {row['ray_mean']:6.2f} "
          f"(peak {row['ray_peak']:3.0f})", flush=True)

from scipy import stats as st
rast = [r["rast_mean"] for r in rows]
ray = [r["ray_mean"] for r in rows]
rho, prho = st.spearmanr(rast, ray)
pear, ppear = st.pearsonr(rast, ray)
slope, intercept = np.polyfit(rast, ray, 1)
json.dump(dict(rows=rows, spearman=rho, spearman_p=prho, pearson=pear,
               slope=slope, intercept=intercept, real_mean_r=38.7, real_peak_r=8.0),
          open(OUT, "w"), indent=1)

print(f"\n=== rasterized vs ray-traced mean structure radius, n={len(rows)} ===")
print(f"  Spearman {rho:+.3f} (p {prho:.3f})   Pearson {pear:+.3f} (p {ppear:.3f})")
print(f"  ray = {slope:.3f} * rasterized + {intercept:.2f}")
print(f"  rasterized spans {min(rast):.1f}-{max(rast):.1f} px; ray-traced {min(ray):.1f}-{max(ray):.1f} px")
print(f"  real reference: mean_r 38.7 px, peak 8 px")
print(f"\nwrote {OUT}")
print("GRANULO VALIDATION COMPLETE")
