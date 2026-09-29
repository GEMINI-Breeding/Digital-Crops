"""Tune germination for the section-18 architecture, then render the strip from the best of it.

The corrected stem architecture closes leaf size (74.5 against a real 75.9) but leaves canopy cover
at 0.995 against 0.947, because larger leaves on fewer nodes still seal the canopy at trial 18's
germination of 0.948. Germination is the lever that reliably moves cover, and lowering it should
pull flowers from 9.61 toward the real 7.57 at the same time.

This is a FIDELITY configuration. Section 17 measured that a more realistic canopy trained a detector
0.098 mAP worse at 10.9 SE, and this one carries fewer labelled boxes than trial 18, so it is not a
training-set recommendation and its detection performance is unmeasured.
"""
import base64, glob, json, os, subprocess, sys
import numpy as np, cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real import camera_pipeline as cp
from syn2real.tile import tile_frame
from syn2real.leafcolour import summarise as leafcolour, REAL as LEAF_REAL
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sam_leaf_size import leaf_masks, N_TILES

BASE = json.load(open("audit/phase5_confirm.json"))["results"]["18"]["overrides"]
ARCH = {"canopy.internode_length_max": "0.0750", "canopy.phyllochron": "6.00",
        "canopy.max_nodes": "7", "leaf.prototype_scale_min": "0.1690",
        "leaf.prototype_scale_max": "0.3040", "flower.bud_break_prob_min": "0.800",
        "flower.bud_break_prob_max": "0.900", "flower.flowers_per_peduncle_min": "3",
        "flower.flowers_per_peduncle_max": "3"}
GERM = [(0.948, 0.948), (0.55, 0.90), (0.40, 0.80), (0.30, 0.70)]
SEEDS = (10300, 10301, 10302)
REAL_COVER, REAL_BOXES, REAL_MAJOR = 0.947, 7.57, 75.9

os.environ.pop("YOLO_OFFLINE", None); os.environ.pop("ULTRALYTICS_OFFLINE", None)
from ultralytics import SAM
sam = SAM("weights/mobile_sam.pt")


def build(glo, ghi, tag, n_frames=3, seeds=None):
    raw, dev, tiles = f"bf_raw_{tag}", f"bf_dev_{tag}", f"bf_tiles_{tag}"
    for d in (raw, dev, tiles):
        os.system(f"rm -rf {d}")
    ov = dict(BASE); ov.update(ARCH)
    ov["canopy.germination_fraction_min"] = f"{glo:.4f}"
    ov["canopy.germination_fraction_max"] = f"{ghi:.4f}"
    flat = [x for kv in ov.items() for x in kv]
    for seed in (seeds or SEEDS):
        r = subprocess.run(["./SyntheticAutotuning", "render", "../config/baseline.cfg", str(seed),
                            "camera.samples", "50", "output.folder", f"../{raw}/"] + flat,
                           capture_output=True, text=True, cwd="build-gpu")
        if r.returncode != 0:
            raise SystemExit(f"render failed: {(r.stderr.strip().splitlines() or ['?'])[-1]}")
    subprocess.run(["env/bin/python", "scripts/develop.py", raw, "--out", dev,
                    "--target-L", str(cp.REAL_FOLIAGE_L)], check=True, capture_output=True)
    written = []
    for i, img in enumerate(sorted(glob.glob(os.path.join(dev, "*_RGB.jpeg")))):
        stem = os.path.basename(img).replace("camA_", "").replace("_RGB.jpeg", "")
        lbl = os.path.join(raw, stem + "_bbox.txt")
        if not os.path.exists(lbl):
            continue
        written += tile_frame(img, lbl, tiles, n_tiles=15, seed=8100 + i,
                              rover_mask_path=os.path.join(raw, "camA_" + stem + "_rover.txt"),
                              ground_mask_path=os.path.join(raw, "camA_" + stem + "_ground.txt"))
    return raw, dev, tiles, written


print(f"{'germination':>13} {'leaf major':>11} {'cover p5':>9} {'cover p50':>10} {'boxes/tile':>11}",
      flush=True)
rows = []
for glo, ghi in GERM:
    tag = f"{glo:.2f}"
    raw, dev, tiles, written = build(glo, ghi, tag)
    cov = np.array([t[1] for t in written]); box = np.array([t[2] for t in written])
    fs = sorted(glob.glob(os.path.join(tiles, "images", "*.jpeg")))
    rng = np.random.default_rng(0)
    sel = [fs[i] for i in rng.choice(len(fs), min(N_TILES, len(fs)), replace=False)]
    masks = []
    for f in sel:
        masks += leaf_masks(sam, f)
    major = float(np.median(np.array(masks)[:, 1]))
    rows.append(dict(germ=[glo, ghi], major=major, cover_p5=float(np.percentile(cov, 5)),
                     cover_p50=float(np.median(cov)), boxes=float(box.mean())))
    print(f"{glo:.2f}-{ghi:.2f} {major:11.1f} {np.percentile(cov,5):9.3f} "
          f"{np.median(cov):10.3f} {box.mean():11.2f}", flush=True)
    for d in (raw, dev, tiles):
        os.system(f"rm -rf {d}")
print(f"{'REAL':>13} {REAL_MAJOR:11.1f} {0.568:9.3f} {REAL_COVER:10.3f} {REAL_BOXES:11.2f}")

best = min(rows, key=lambda r: abs(r["cover_p50"] - REAL_COVER) / 0.05
           + abs(r["boxes"] - REAL_BOXES) / REAL_BOXES)
glo, ghi = best["germ"]
print(f"\nrendering the strip at germination {glo:.2f}-{ghi:.2f} "
      f"(cover {best['cover_p50']:.3f}, boxes {best['boxes']:.2f}, leaf {best['major']:.1f})",
      flush=True)

raw, dev, tiles, written = build(glo, ghi, "final", seeds=range(10400, 10410))
cov = np.array([t[1] for t in written]); box = np.array([t[2] for t in written])
lc = leafcolour(tiles)
print(f"\n{len(written)} tiles, {int(box.sum())} boxes", flush=True)
print(f"exact cover  p5 {np.percentile(cov,5):.3f}  p50 {np.median(cov):.3f}  "
      f"p95 {np.percentile(cov,95):.3f}   (real 0.568 / 0.947 / 0.984)", flush=True)
print(f"boxes/tile   mean {box.mean():.2f}   (real 7.57)", flush=True)
print(f"leaf-patch   a* spread {lc['a_spread']:.2f} (real {LEAF_REAL['a_spread']:.2f}); "
      f"L* spread {lc['L_spread_within_tile']:.2f} (real {LEAF_REAL['L_spread_within_tile']:.2f}); "
      f"median L* {lc['L_p50']:.2f} (real {LEAF_REAL['L_p50']:.2f})", flush=True)

order = sorted(zip([t[1] for t in written], [t[0] for t in written]))
panels = []
for q in (0.25, 0.50, 0.75):
    c, name = order[int(q * (len(order) - 1))]
    hit = glob.glob(os.path.join(tiles, "images", name + ".*"))[0]
    panels.append(cv2.resize(cv2.imread(hit), (200, 200), interpolation=cv2.INTER_AREA))
    print(f"  strip pick cover={c:.3f}  {os.path.basename(hit)}", flush=True)
ok, buf = cv2.imencode(".jpg", np.hstack(panels), [int(cv2.IMWRITE_JPEG_QUALITY), 88])
open("audit/strip_fidelity.b64", "w").write(base64.b64encode(buf.tobytes()).decode("ascii"))
json.dump(dict(germination=[glo, ghi], arch=ARCH, rows=rows), open("audit/best_fidelity.json", "w"), indent=1)
for d in (raw, dev, tiles):
    os.system(f"rm -rf {d}")
print("\nwrote audit/strip_fidelity.b64")
print("BEST FIDELITY STRIP COMPLETE")
