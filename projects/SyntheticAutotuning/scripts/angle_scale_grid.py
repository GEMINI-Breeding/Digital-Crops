"""Is the canopy's problem leaf SIZE or leaf ANGLE?

Three sweeps raised leaf.prototype_scale by x1.96 from trial 18 and apparent leaf size moved only
52 -> 65 px against a real 75.9, most of that from opening the canopy rather than from the scale.
Then the leaf elevation angle turned out to be 48.0 deg -- indistinguishable from a UNIFORM
distribution (48.3), which is a modelling default rather than a property of cowpea. Cowpea is
planophile, and the Beta pair (2.77, 1.172) puts the mean at 33.4 deg, worth cos(33.4)/cos(48.0) =
1.25x of projected length in a nadir view.

If angle is the real cause then the correct canopy is ORIGINAL-SIZE leaves lying flatter, not
oversized leaves at a random orientation -- which would render the same from above and be wrong in
every other respect, including a compound leaf of ~33 cm at the top of the plausible range.

So this grid crosses scale with the planophile setting, starting from trial 18's own value. The
question it answers is which combination reaches real leaf size, not whether one of them does.
"""
import glob, json, os, subprocess, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real import camera_pipeline as cp
from syn2real.tile import tile_frame
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sam_leaf_size import leaf_masks, N_TILES

BASE = json.load(open("audit/phase5_confirm.json"))["results"]["18"]["overrides"]
PLANOPHILE = ("2.7700", "1.1720")
CONFIGS = [
    ("trial18 scale, planophile",  0.0938, 0.1690, True,  0.35, 0.85),
    ("trial18 scale, uniform",     0.0938, 0.1690, False, 0.35, 0.85),
    ("x1.33 scale, planophile",    0.1250, 0.2250, True,  0.35, 0.85),
    ("x1.33 scale, planophile",    0.1250, 0.2250, True,  0.45, 0.90),
]
SEEDS = (9800, 9801, 9802)
REAL = dict(major=75.9, per_tile=68.2, cover_p50=0.947, cover_p5=0.568, boxes=7.57)

os.environ.pop("YOLO_OFFLINE", None); os.environ.pop("ULTRALYTICS_OFFLINE", None)
from ultralytics import SAM
sam = SAM("weights/mobile_sam.pt")

print(f"{'configuration':30s} {'germ':>10} {'leaf major':>11} {'leaves/tile':>12} "
      f"{'cover p5':>9} {'cover p50':>10} {'boxes/tile':>11}", flush=True)
rows = []
for label, lo, hi, plano, glo, ghi in CONFIGS:
    tag = f"{lo:.3f}_{int(plano)}_{glo:.2f}"
    raw, dev, tiles = f"asg_raw_{tag}", f"asg_dev_{tag}", f"asg_tiles_{tag}"
    for d in (raw, dev, tiles):
        os.system(f"rm -rf {d}")
    ov = dict(BASE)
    ov["leaf.prototype_scale_min"] = f"{lo:.4f}"
    ov["leaf.prototype_scale_max"] = f"{hi:.4f}"
    ov["canopy.germination_fraction_min"] = f"{glo:.4f}"
    ov["canopy.germination_fraction_max"] = f"{ghi:.4f}"
    if plano:
        ov["leaf.set_angle_distribution"] = "1"
        ov["leaf.angle_beta_mu"], ov["leaf.angle_beta_nu"] = PLANOPHILE
    flat = [x for kv in ov.items() for x in kv]
    for seed in SEEDS:
        r = subprocess.run(["./SyntheticAutotuning", "render", "../config/baseline.cfg", str(seed),
                            "camera.samples", "50", "output.folder", f"../{raw}/"] + flat,
                           capture_output=True, text=True, cwd="build-gpu")
        if r.returncode != 0:
            raise SystemExit(f"render failed ({label}): {(r.stderr.strip().splitlines() or ['?'])[-1]}")
    subprocess.run(["env/bin/python", "scripts/develop.py", raw, "--out", dev,
                    "--target-L", str(cp.REAL_FOLIAGE_L)], check=True, capture_output=True)
    written = []
    for i, img in enumerate(sorted(glob.glob(os.path.join(dev, "*_RGB.jpeg")))):
        stem = os.path.basename(img).replace("camA_", "").replace("_RGB.jpeg", "")
        lbl = os.path.join(raw, stem + "_bbox.txt")
        if not os.path.exists(lbl):
            continue
        written += tile_frame(img, lbl, tiles, n_tiles=15, seed=7100 + i,
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
    rows.append(dict(label=label, scale=[lo, hi], planophile=plano, germ=[glo, ghi],
                     leaf_major=major, leaves_per_tile=per_tile,
                     cover_p5=float(np.percentile(cov, 5)), cover_p50=float(np.median(cov)),
                     boxes=float(box.mean())))
    print(f"{label:30s} {glo:.2f}-{ghi:.2f} {major:11.1f} {per_tile:12.1f} "
          f"{np.percentile(cov,5):9.3f} {np.median(cov):10.3f} {box.mean():11.2f}", flush=True)
    for d in (raw, dev, tiles):
        os.system(f"rm -rf {d}")

json.dump(dict(real=REAL, rows=rows), open("audit/angle_scale_grid.json", "w"), indent=1)
print(f"{'REAL':30s} {'':>10} {REAL['major']:11.1f} {REAL['per_tile']:12.1f} "
      f"{REAL['cover_p5']:9.3f} {REAL['cover_p50']:10.3f} {REAL['boxes']:11.2f}")
print("ANGLE SCALE GRID COMPLETE")
