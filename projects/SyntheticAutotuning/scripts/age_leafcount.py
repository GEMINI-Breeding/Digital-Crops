"""Fewer leaves per plant: the ratio that scale and germination cannot change.

At matched canopy cover -- 0.951 synthetic against a real 0.947 -- the synthetic canopy shows 111
leaves per tile against a real 68. Cover divided by leaf count is visible area per leaf: 0.00856
against 0.01389, a ratio of 1.62, whose square root is 1.27 and that is the leaf-size gap. A canopy
with 1.6x as many leaves at the same cover must show 1.6x less of each.

Neither lever tried today changes that ratio. Raising leaf scale raises cover, which forces
germination down, and germination removes whole plants -- cutting leaf count and cover together and
leaving leaves-per-unit-cover where it started. That is why x1.96 on scale moved apparent size from
52 to 65 px and no further.

canopy.age sets how many phytomers a plant has produced, so it changes leaves per plant at fixed
plant count. It has been pinned at 37 by trial 18 through every sweep in this campaign. Fewer nodes
should also carry fewer flowers, which currently sit at 13.3 against a real 7.57.
"""
import glob, json, os, subprocess, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real import camera_pipeline as cp
from syn2real.tile import tile_frame
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sam_leaf_size import leaf_masks, N_TILES

BASE = json.load(open("audit/phase5_confirm.json"))["results"]["18"]["overrides"]
# Scale and germination held at the best configuration found so far (cover 0.951 vs a real 0.947),
# so age is the only thing moving.
FIXED = {"leaf.prototype_scale_min": "0.1250", "leaf.prototype_scale_max": "0.2250",
         "canopy.germination_fraction_min": "0.35", "canopy.germination_fraction_max": "0.85",
         "leaf.set_angle_distribution": "1", "leaf.angle_beta_mu": "2.7700",
         "leaf.angle_beta_nu": "1.1720"}
AGES = [37, 32, 28, 24]
SEEDS = (9970, 9971, 9972)
REAL = dict(major=75.9, per_tile=68.2, cover_p50=0.947, cover_p5=0.568, boxes=7.57)

os.environ.pop("YOLO_OFFLINE", None); os.environ.pop("ULTRALYTICS_OFFLINE", None)
from ultralytics import SAM
sam = SAM("weights/mobile_sam.pt")

print("scale and germination fixed at the best configuration; only canopy.age varies\n")
print(f"{'age':>5} {'leaf major':>11} {'leaves/tile':>12} {'area/leaf':>10} {'cover p5':>9} "
      f"{'cover p50':>10} {'boxes/tile':>11}", flush=True)
rows = []
for age in AGES:
    raw, dev, tiles = f"al_raw_{age}", f"al_dev_{age}", f"al_tiles_{age}"
    for d in (raw, dev, tiles):
        os.system(f"rm -rf {d}")
    ov = dict(BASE); ov.update(FIXED); ov["canopy.age"] = str(age)
    flat = [x for kv in ov.items() for x in kv]
    for seed in SEEDS:
        r = subprocess.run(["./SyntheticAutotuning", "render", "../config/baseline.cfg", str(seed),
                            "camera.samples", "50", "output.folder", f"../{raw}/"] + flat,
                           capture_output=True, text=True, cwd="build-gpu")
        if r.returncode != 0:
            raise SystemExit(f"render failed at age {age}: {(r.stderr.strip().splitlines() or ['?'])[-1]}")
    subprocess.run(["env/bin/python", "scripts/develop.py", raw, "--out", dev,
                    "--target-L", str(cp.REAL_FOLIAGE_L)], check=True, capture_output=True)
    written = []
    for i, img in enumerate(sorted(glob.glob(os.path.join(dev, "*_RGB.jpeg")))):
        stem = os.path.basename(img).replace("camA_", "").replace("_RGB.jpeg", "")
        lbl = os.path.join(raw, stem + "_bbox.txt")
        if not os.path.exists(lbl):
            continue
        written += tile_frame(img, lbl, tiles, n_tiles=15, seed=7500 + i,
                              rover_mask_path=os.path.join(raw, "camA_" + stem + "_rover.txt"),
                              ground_mask_path=os.path.join(raw, "camA_" + stem + "_ground.txt"))
    cov = np.array([t[1] for t in written]); box = np.array([t[2] for t in written])
    fs = sorted(glob.glob(os.path.join(tiles, "images", "*.jpeg")))
    rng = np.random.default_rng(0)
    if len(fs) > N_TILES:
        fs = [fs[i] for i in rng.choice(len(fs), N_TILES, replace=False)]
    masks = []
    for f in fs:
        masks += leaf_masks(sam, f)
    a = np.array(masks)
    major, per_tile = float(np.median(a[:, 1])), len(masks) / len(fs)
    cover50 = float(np.median(cov))
    area_per_leaf = cover50 / max(per_tile, 1e-9)
    rows.append(dict(age=age, leaf_major=major, leaves_per_tile=per_tile,
                     area_per_leaf=area_per_leaf, cover_p5=float(np.percentile(cov, 5)),
                     cover_p50=cover50, boxes=float(box.mean())))
    print(f"{age:5d} {major:11.1f} {per_tile:12.1f} {area_per_leaf:10.5f} "
          f"{np.percentile(cov,5):9.3f} {cover50:10.3f} {box.mean():11.2f}", flush=True)
    for d in (raw, dev, tiles):
        os.system(f"rm -rf {d}")

json.dump(dict(real=REAL, fixed=FIXED, rows=rows), open("audit/age_leafcount.json", "w"), indent=1)
print(f"{'REAL':>5} {REAL['major']:11.1f} {REAL['per_tile']:12.1f} "
      f"{REAL['cover_p50']/REAL['per_tile']:10.5f} {REAL['cover_p5']:9.3f} "
      f"{REAL['cover_p50']:10.3f} {REAL['boxes']:11.2f}")
print("\narea/leaf is cover divided by leaf count -- the ratio scale and germination cannot move.")
print("AGE LEAFCOUNT COMPLETE")
