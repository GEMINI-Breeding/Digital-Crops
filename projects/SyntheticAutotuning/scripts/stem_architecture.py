"""Break the leaf-count-to-size ratio by changing stem architecture.

The cowpea library gives each node a trifoliate leaf with 0.10-0.16 m leaflets and spaces the nodes
0.025 m apart, so a leaf spans four to six times its own spacing. Real cowpea runs 5-10 cm internodes
against comparable leaflets. That is why the canopy shows 1.6x too many leaves at the same cover, and
why no previously exposed parameter fixed it: germination and age remove leaves and cover together,
and leaf scale alone would need a 0.24-0.43 m leaf.

Node count and internode length have to move together, because plant height is the product of the
two and is pinned at a measured 0.54 m. Halving the nodes and doubling the internode gives the same
height with half the leaves, and leaf scale then makes up the lost cover.

None of these needed a library edit: internode_length_max, phyllochron_min and max_nodes are
ShootParameters fields reachable through the getCurrentShootParameters path this project already
uses for leaf and flower scale. They simply had no config keys.
"""
import glob, json, os, subprocess, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real import camera_pipeline as cp
from syn2real.tile import tile_frame
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sam_leaf_size import leaf_masks, N_TILES

BASE = json.load(open("audit/phase5_confirm.json"))["results"]["18"]["overrides"]
# Corrected stem architecture leaves the plant with too few flowering sites: 20 nodes became 7, and
# flowers fell from 18.19 per tile to 0.28 against a real 7.57. Fewer nodes cannot be undone without
# undoing the leaf fix, so flower production PER NODE has to rise instead -- bud break probability
# and flowers per peduncle, both already exposed. Real cowpea evidently sets far more fruit per node
# than this model does.
#
# name, internode, phyllochron, max_nodes, leaf_lo, leaf_hi, bud_lo, bud_hi, flowers_per_peduncle
CONFIGS = [
    ("2x stem, leaf1.4, bud .55 fpp2", 0.050, 4.0, 10, 0.1310, 0.2360, 0.50, 0.60, 2),
    ("2x stem, leaf1.4, bud .85 fpp2", 0.050, 4.0, 10, 0.1310, 0.2360, 0.80, 0.90, 2),
    ("3x stem, leaf1.8, bud .85 fpp3", 0.075, 6.0,  7, 0.1690, 0.3040, 0.80, 0.90, 3),
    ("3x stem, leaf1.8, bud 1.0 fpp4", 0.075, 6.0,  7, 0.1690, 0.3040, 0.95, 1.00, 4),
]
SEEDS = (10200, 10201, 10202)
REAL = dict(major=75.9, per_tile=68.2, area_per_leaf=0.947 / 68.2, cover_p50=0.947, boxes=7.57)

os.environ.pop("YOLO_OFFLINE", None); os.environ.pop("ULTRALYTICS_OFFLINE", None)
from ultralytics import SAM
sam = SAM("weights/mobile_sam.pt")

print(f"target area/leaf {REAL['area_per_leaf']:.5f}; plant height must stay near 0.54 m\n")
print(f"{'configuration':32s} {'height':>7} {'leaf major':>11} {'leaves/tile':>12} {'area/leaf':>10} "
      f"{'cover p50':>10} {'boxes':>7}", flush=True)
rows = []
for label, inter, phyllo, nodes, llo, lhi, bud_lo, bud_hi, fpp in CONFIGS:
    tag = label.replace(" ", "_").replace(",", "").replace("(", "").replace(")", "")[:24]
    raw, dev, tiles = f"sa_raw_{tag}", f"sa_dev_{tag}", f"sa_tiles_{tag}"
    for d in (raw, dev, tiles):
        os.system(f"rm -rf {d}")
    ov = dict(BASE)
    ov["leaf.prototype_scale_min"] = f"{llo:.4f}"
    ov["leaf.prototype_scale_max"] = f"{lhi:.4f}"
    if inter is not None:
        ov["canopy.internode_length_max"] = f"{inter:.4f}"
        ov["canopy.phyllochron"] = f"{phyllo:.2f}"
        ov["canopy.max_nodes"] = str(nodes)
    ov["flower.bud_break_prob_min"] = f"{bud_lo:.3f}"
    ov["flower.bud_break_prob_max"] = f"{bud_hi:.3f}"
    ov["flower.flowers_per_peduncle_min"] = str(fpp)
    ov["flower.flowers_per_peduncle_max"] = str(fpp)
    flat = [x for kv in ov.items() for x in kv]
    height = float("nan")
    for seed in SEEDS:
        r = subprocess.run(["./SyntheticAutotuning", "render", "../config/baseline.cfg", str(seed),
                            "camera.samples", "50", "output.folder", f"../{raw}/"] + flat,
                           capture_output=True, text=True, cwd="build-gpu")
        if r.returncode != 0:
            raise SystemExit(f"render failed ({label}): {(r.stderr.strip().splitlines() or ['?'])[-1]}")
        for line in r.stdout.splitlines():
            if "DIAG plant_height" in line:
                height = float(line.split("median=")[1].split()[0])
    subprocess.run(["env/bin/python", "scripts/develop.py", raw, "--out", dev,
                    "--target-L", str(cp.REAL_FOLIAGE_L)], check=True, capture_output=True)
    written = []
    for i, img in enumerate(sorted(glob.glob(os.path.join(dev, "*_RGB.jpeg")))):
        stem = os.path.basename(img).replace("camA_", "").replace("_RGB.jpeg", "")
        lbl = os.path.join(raw, stem + "_bbox.txt")
        if not os.path.exists(lbl):
            continue
        written += tile_frame(img, lbl, tiles, n_tiles=15, seed=7900 + i,
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
    apl = cover50 / max(per_tile, 1e-9)
    rows.append(dict(label=label, internode=inter, phyllochron=phyllo, max_nodes=nodes,
                     leaf=[llo, lhi], bud=[bud_lo, bud_hi], fpp=fpp, height=height, leaf_major=major, leaves_per_tile=per_tile,
                     area_per_leaf=apl, cover_p50=cover50, boxes=float(box.mean())))
    print(f"{label:32s} {height:7.3f} {major:11.1f} {per_tile:12.1f} {apl:10.5f} "
          f"{cover50:10.3f} {box.mean():7.2f}", flush=True)
    for d in (raw, dev, tiles):
        os.system(f"rm -rf {d}")

json.dump(dict(real=REAL, rows=rows), open("audit/stem_flowers.json", "w"), indent=1)
print(f"{'REAL':32s} {0.54:7.3f} {REAL['major']:11.1f} {REAL['per_tile']:12.1f} "
      f"{REAL['area_per_leaf']:10.5f} {REAL['cover_p50']:10.3f} {REAL['boxes']:7.2f}")
print("\narea/leaf is the ratio no previously exposed parameter could move (0.0080-0.0089 across")
print("every leaf scale, germination and canopy age tried).")
print("STEM ARCHITECTURE COMPLETE")
