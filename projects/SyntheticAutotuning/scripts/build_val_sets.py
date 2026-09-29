"""Develop and tile the eight validation configurations into comparable datasets."""
import glob, json, os, subprocess, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real import camera_pipeline as cp
from syn2real.tile import tile_frame

GAIN = cp.DEVELOP_GAIN
report = {}
for d in sorted(glob.glob("frames_val/cfg*")):
    name = os.path.basename(d)
    dev = f"{d}_dev"
    subprocess.run([sys.executable, "scripts/develop.py", d, "--out", dev,
                    "--target-L", str(cp.REAL_FOLIAGE_L)], check=True, capture_output=True)
    out = f"synthetic_{name}"
    os.system(f"rm -rf {out}")
    written = []
    for i, img in enumerate(sorted(glob.glob(os.path.join(dev, "*_RGB.jpeg")))):
        stem = os.path.basename(img).replace("camA_", "").replace("_RGB.jpeg", "")
        label = os.path.join(d, stem + "_bbox.txt")
        rover = os.path.join(d, "camA_" + stem + "_rover.txt")
        ground = os.path.join(d, "camA_" + stem + "_ground.txt")
        if not os.path.exists(label):
            continue
        written += tile_frame(img, label, out, n_tiles=20, seed=3000 + i,
                              rover_mask_path=rover if os.path.exists(rover) else None,
                              ground_mask_path=ground if os.path.exists(ground) else None)
    cov = np.array([t[1] for t in written]); box = np.array([t[2] for t in written])
    report[name] = dict(tiles=len(written), boxes=int(box.sum()),
                        cover_p50=float(np.median(cov)), boxes_per_tile=float(box.mean()))
    print(f"{name}: {len(written)} tiles, {int(box.sum())} boxes, "
          f"cover p50 {np.median(cov):.3f}, boxes/tile {box.mean():.2f}", flush=True)
json.dump(report, open("audit/val_sets.json", "w"), indent=1)
print("BUILD COMPLETE")
