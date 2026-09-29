"""Tile the v21 developed frames, selecting tiles by EXACT ground masks."""
import glob, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real.tile import tile_frame

DEV, RAW, OUT = "frames_v21_dev", "frames_v21", "synthetic_v21"
written = []
for i, img in enumerate(sorted(glob.glob(os.path.join(DEV, "*_RGB.jpeg")))):
    stem = os.path.basename(img).replace("camA_", "").replace("_RGB.jpeg", "")
    label  = os.path.join(RAW, stem + "_bbox.txt")
    rover  = os.path.join(RAW, "camA_" + stem + "_rover.txt")
    ground = os.path.join(RAW, "camA_" + stem + "_ground.txt")
    if not os.path.exists(label):
        print(f"SKIP {stem}: no labels", flush=True); continue
    w = tile_frame(img, label, OUT, n_tiles=15, seed=2000 + i,
                   rover_mask_path=rover if os.path.exists(rover) else None,
                   ground_mask_path=ground if os.path.exists(ground) else None)
    written += w
    print(f"{stem}: {len(w)} tiles, {sum(t[2] for t in w)} boxes, cover {min(t[1] for t in w):.3f}-{max(t[1] for t in w):.3f}", flush=True)
import json, numpy as np
cov=np.array([t[1] for t in written]); box=np.array([t[2] for t in written])
json.dump([{"name":t[0],"cover":t[1],"boxes":t[2]} for t in written], open("audit/tiles_v21.json","w"))
print(f"TOTAL {len(written)} tiles, {int(box.sum())} boxes", flush=True)
print(f"EXACT tile cover  p5 {np.percentile(cov,5):.3f}  p50 {np.median(cov):.3f}  p95 {np.percentile(cov,95):.3f}", flush=True)
print(f"boxes/tile        p5 {np.percentile(box,5):.1f}  p50 {np.median(box):.1f}  p95 {np.percentile(box,95):.1f}  mean {box.mean():.2f}", flush=True)
print(f"REAL              cover p5 0.568 p50 0.947 p95 0.984 | boxes/tile mean 7.57", flush=True)
print("TILE COMPLETE", flush=True)
