"""Larger leaves, fewer plants: the two must move together.

SAM measures synthetic leaf major axis at 52.1 tile px against a real 75.9 -- 1.46x too small -- with
2.3x as many leaves per tile. Enlarging leaves alone seals the canopy: at the scale SAM asks for,
cover goes to 0.991 against a real 0.947 and flower density barely moves. Fewer plants pays for the
larger leaves and moves four quantities toward real at once: leaf size up, leaf count down, canopy
cover back to 0.947, and flower density down from 18.6 toward 7.57.

Germination rather than spacing is the density lever because it is a per-plant stochastic draw, so a
RANGE also supplies the sparse-canopy tail the synthetic set has never had (real cover p5 0.568
against this build's 0.858).

Leaf size is measured with SAM, not granulometry. Granulometry called this canopy a match to within
1 px while its leaves were 1.46x too small, because many small overlapping leaves produce the same
bright-structure size as fewer large ones.
"""
import glob, json, os, subprocess, sys
import numpy as np, cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real import camera_pipeline as cp
from syn2real.tile import tile_frame
from syn2real.leafcolour import summarise as leafcolour

BASE = json.load(open("audit/phase5_confirm.json"))["results"]["18"]["overrides"]
# 0.1369-0.2467 gave leaflets of 62 px at cover 0.845 -- sparser than real, so not occlusion-limited
# -- against a real 75.9. That is x1.22 short, so the scale goes up by the same factor. The earlier
# x1.46 was measured against a SEALED canopy (cover 0.988) where SAM reads truncated leaf fragments;
# validated against the renderer's own labels, SAM recovers only ~0.15 of a compound leaf's extent
# where ~0.35 would be a whole leaflet, so it under-reads absolute size and is only a fair
# comparator at matched occlusion.
# x1.10 on 0.1670-0.3010. At germination 0.30-0.75 that sweep matched leaf COUNT (75.8 vs 68.2) and
# came within 10% on SIZE (69.3 vs 75.9) while cover sat at 0.791 against 0.947 -- and those are the
# same fact, not two: leaf area scales as the square, (69.3/75.9)^2 = 0.83 against a cover ratio of
# 0.791/0.947 = 0.835. So x1.10 on linear size should raise cover by 1.20 to about 0.95 and put leaf
# size on 75.9 at the same time.
LEAF_LO, LEAF_HI = 0.1837, 0.3311
GERM = [(0.25, 0.70), (0.30, 0.75), (0.35, 0.85)]
SEEDS = (9600, 9601, 9602)
REAL = dict(major=75.9, per_tile=68.2, cover_p50=0.947, cover_p5=0.568, boxes=7.57)

os.environ.pop("YOLO_OFFLINE", None); os.environ.pop("ULTRALYTICS_OFFLINE", None)
from ultralytics import SAM
sam = SAM("weights/mobile_sam.pt")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sam_leaf_size import leaf_masks, N_TILES


def sam_stats(tiles):
    fs = sorted(glob.glob(os.path.join(tiles, "images", "*.jpeg")))
    rng = np.random.default_rng(0)
    if len(fs) > N_TILES:
        fs = [fs[i] for i in rng.choice(len(fs), N_TILES, replace=False)]
    rows = []
    for f in fs:
        rows += leaf_masks(sam, f)
    if not rows:
        return float("nan"), float("nan")
    a = np.array(rows)
    return float(np.median(a[:, 1])), len(rows) / len(fs)


#: What the scale was before this run, so the ratio in the log is DERIVED rather than a literal
#: that goes stale the next time the constants move -- which it has done twice.
PREV_LEAF = (0.1670, 0.3010)
_ratio = ((LEAF_LO + LEAF_HI) / 2) / ((PREV_LEAF[0] + PREV_LEAF[1]) / 2)
print(f"leaf scale {LEAF_LO:.4f}-{LEAF_HI:.4f}  "
      f"(x{_ratio:.2f} on {PREV_LEAF[0]:.4f}-{PREV_LEAF[1]:.4f})")
print("SAM under-reads absolute leaf size (0.15 of a compound leaf where a leaflet is ~0.35),\n"
      "so it is a fair comparator only at matched occlusion -- compare rows at similar cover.\n")
print(f"{'germination':>14} {'leaf major':>11} {'leaves/tile':>12} {'cover p5':>9} {'cover p50':>10} "
      f"{'boxes/tile':>11}", flush=True)
rows = []
for glo, ghi in GERM:
    tag = f"{glo:.2f}_{ghi:.2f}"
    raw, dev, tiles = f"ld_raw_{tag}", f"ld_dev_{tag}", f"ld_tiles_{tag}"
    for d in (raw, dev, tiles):
        os.system(f"rm -rf {d}")
    ov = dict(BASE)
    ov["leaf.prototype_scale_min"] = f"{LEAF_LO:.4f}"
    ov["leaf.prototype_scale_max"] = f"{LEAF_HI:.4f}"
    ov["canopy.germination_fraction_min"] = f"{glo:.4f}"
    ov["canopy.germination_fraction_max"] = f"{ghi:.4f}"
    flat = [x for kv in ov.items() for x in kv]
    for seed in SEEDS:
        r = subprocess.run(["./SyntheticAutotuning", "render", "../config/baseline.cfg", str(seed),
                            "camera.samples", "50", "output.folder", f"../{raw}/"] + flat,
                           capture_output=True, text=True, cwd="build-gpu")
        if r.returncode != 0:
            raise SystemExit(f"render failed at germ {glo}-{ghi}: "
                             f"{(r.stderr.strip().splitlines() or ['?'])[-1]}")
    subprocess.run(["env/bin/python", "scripts/develop.py", raw, "--out", dev,
                    "--target-L", str(cp.REAL_FOLIAGE_L)], check=True, capture_output=True)
    written = []
    for i, img in enumerate(sorted(glob.glob(os.path.join(dev, "*_RGB.jpeg")))):
        stem = os.path.basename(img).replace("camA_", "").replace("_RGB.jpeg", "")
        label = os.path.join(raw, stem + "_bbox.txt")
        if not os.path.exists(label):
            continue
        written += tile_frame(img, label, tiles, n_tiles=15, seed=6500 + i,
                              rover_mask_path=os.path.join(raw, "camA_" + stem + "_rover.txt"),
                              ground_mask_path=os.path.join(raw, "camA_" + stem + "_ground.txt"))
    cov = np.array([t[1] for t in written]); box = np.array([t[2] for t in written])
    major, per_tile = sam_stats(tiles)
    lc = leafcolour(tiles)
    rows.append(dict(germ_min=glo, germ_max=ghi, leaf_major=major, leaves_per_tile=per_tile,
                     cover_p5=float(np.percentile(cov, 5)), cover_p50=float(np.median(cov)),
                     boxes=float(box.mean()), a_spread=lc["a_spread"],
                     L_spread=lc["L_spread_within_tile"], tiles=len(written)))
    print(f"{glo:.2f}-{ghi:.2f} {major:11.1f} {per_tile:12.1f} {np.percentile(cov,5):9.3f} "
          f"{np.median(cov):10.3f} {box.mean():11.2f}", flush=True)
    for d in (raw, dev, tiles):
        os.system(f"rm -rf {d}")

json.dump(dict(real=REAL, leaf_scale=[LEAF_LO, LEAF_HI], rows=rows),
          open("audit/leaf_density_joint3.json", "w"), indent=1)
print(f"{'REAL':>14} {REAL['major']:11.1f} {REAL['per_tile']:12.1f} {REAL['cover_p5']:9.3f} "
      f"{REAL['cover_p50']:10.3f} {REAL['boxes']:11.2f}")
best = min(rows, key=lambda r: abs(r["cover_p50"] - REAL["cover_p50"]) / 0.05
           + abs(r["boxes"] - REAL["boxes"]) / REAL["boxes"])
print(f"\nclosest on cover and flower density: germination "
      f"{best['germ_min']:.2f}-{best['germ_max']:.2f}  cover {best['cover_p50']:.3f} "
      f"(p5 {best['cover_p5']:.3f})  boxes {best['boxes']:.2f}  leaf major {best['leaf_major']:.1f}")
print("LEAF DENSITY JOINT COMPLETE")
