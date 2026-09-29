"""Are synthetic leaves small, or are they being split down the midrib?

SAM reports 128.5 leaf objects per synthetic tile against a real 68.2 -- a ratio of 1.88 -- at a
size ratio of 75.9/55.2 = 1.375. And sqrt(1.88) = 1.371. Halving a leaf's area drops its linear size
by sqrt(2) and doubles the object count, so both numbers follow from one cause: each synthetic leaf
being segmented into about two pieces.

The renderer gives venation its own spectrum -- 0.85 lamina + 0.15 yellow, with transmissivity
cleared so it does not glow from behind -- specifically so the midrib does not disappear. Drawn too
strongly that midrib splits a leaflet lengthwise, for a segmenter and for a viewer.

PREDICTION, stated before the run: if venation is the cause, removing it should give leaf major
~78 px (55.2 x sqrt 2) and ~64 leaves per tile (128.5 / 2). If instead size and count barely move,
venation is not the cause and the leaves really are small.
"""
import glob, json, os, subprocess, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real import camera_pipeline as cp
from syn2real.tile import tile_frame
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sam_leaf_size import leaf_masks, N_TILES

BASE = json.load(open("audit/phase5_confirm.json"))["results"]["18"]["overrides"]
# The control row of the angle/scale grid: trial 18 scale, uniform angle, germination 0.35-0.85,
# which measured leaf major 55.2 and 128.5 leaves/tile.
FIXED = {"canopy.germination_fraction_min": "0.35", "canopy.germination_fraction_max": "0.85"}
CONFIGS = [
    ("veins 0.15 yellow, opaque (current)", "0.15", "1"),
    ("veins 0.07 yellow, opaque",           "0.07", "1"),
    ("veins 0.15 yellow, transmissive",     "0.15", "0"),
    ("veins off (lamina spectrum)",         "0.00", "1"),
]
SEEDS = (9900, 9901, 9902)

os.environ.pop("YOLO_OFFLINE", None); os.environ.pop("ULTRALYTICS_OFFLINE", None)
from ultralytics import SAM
sam = SAM("weights/mobile_sam.pt")

print("prediction if venation splits leaves: major ~78 px, ~64 leaves/tile\n")
print(f"{'configuration':38s} {'leaf major':>11} {'leaves/tile':>12} {'cover p50':>10} {'boxes/tile':>11}",
      flush=True)
rows = []
for label, yellow, opaque in CONFIGS:
    tag = f"v{yellow}_{opaque}"
    raw, dev, tiles = f"vt_raw_{tag}", f"vt_dev_{tag}", f"vt_tiles_{tag}"
    for d in (raw, dev, tiles):
        os.system(f"rm -rf {d}")
    ov = dict(BASE); ov.update(FIXED)
    ov["leaf.vein_yellow_fraction"] = yellow
    ov["leaf.vein_opaque"] = opaque
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
        written += tile_frame(img, lbl, tiles, n_tiles=15, seed=7300 + i,
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
    rows.append(dict(label=label, yellow=float(yellow), opaque=int(opaque), leaf_major=major,
                     leaves_per_tile=per_tile, cover_p50=float(np.median(cov)),
                     boxes=float(box.mean())))
    print(f"{label:38s} {major:11.1f} {per_tile:12.1f} {np.median(cov):10.3f} {box.mean():11.2f}",
          flush=True)
    for d in (raw, dev, tiles):
        os.system(f"rm -rf {d}")

json.dump(dict(rows=rows, real=dict(major=75.9, per_tile=68.2)), open("audit/vein_test.json", "w"), indent=1)
print(f"{'REAL':38s} {75.9:11.1f} {68.2:12.1f} {0.947:10.3f} {7.57:11.2f}")
base, off = rows[0], rows[-1]
print(f"\nveins off vs current: major {base['leaf_major']:.1f} -> {off['leaf_major']:.1f} "
      f"({off['leaf_major']/base['leaf_major']:.2f}x), "
      f"count {base['leaves_per_tile']:.1f} -> {off['leaves_per_tile']:.1f} "
      f"({off['leaves_per_tile']/base['leaves_per_tile']:.2f}x)")
print("predicted if splitting: 1.41x on size, 0.50x on count")
print("VEIN TEST COMPLETE")
