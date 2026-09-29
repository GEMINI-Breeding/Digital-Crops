"""Tile the v17 renders into the 640x640 set, and report what came out."""
import glob, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real.tile import tile_frame

FRAMES, OUT = "frames_v17", "synthetic_v17"
written = []
for i, img in enumerate(sorted(glob.glob(os.path.join(FRAMES, "*_RGB.jpeg")))):
    stem = os.path.basename(img).replace("camA_", "").replace("_RGB.jpeg", "")
    label = os.path.join(FRAMES, stem + "_bbox.txt")
    rover = os.path.join(FRAMES, "camA_" + stem + "_rover.txt")
    if not os.path.exists(label):
        print(f"SKIP {stem}: no label file", flush=True)
        continue
    w = tile_frame(img, label, OUT, n_tiles=15, seed=1000 + i,
                   rover_mask_path=rover if os.path.exists(rover) else None)
    written += w
    print(f"{stem}: {len(w)} tiles, {sum(t[2] for t in w)} boxes", flush=True)
print(f"TOTAL {len(written)} tiles, {sum(t[2] for t in written)} boxes", flush=True)
print("TILE COMPLETE", flush=True)
