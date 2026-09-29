"""Build label-convention variants from ONE set of images, to separate labelling from realism.

Synthetic labels are exact; human labels are not. The renderer marks every flower object it can see
a pixel of, while an annotator marks what they can readily see and skip what they cannot -- so
"boxes per tile" is not the same quantity on the two sides, and matching it may be matching the
wrong thing. That would explain why distance-from-real predicts nothing across the validation
configs (spearman -0.02 for box count, -0.24 for cover).

Nothing here re-renders. The imagery is identical across variants; only the labelling convention
changes, which is the one comparison none of the experiments so far has isolated.

Two levers, both already in the tiler:
  min_box_px   -- the annotator's visibility floor. Also a partial occlusion filter, since a
                  bounding box is built from visible pixels and an occluded flower yields a small box.
  min_visible  -- how much of a box must survive the tile edge to be kept.
"""
import glob, json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real.tile import tile_frame

DEV, RAW = "frames_v18", "frames_v18"
VARIANTS = [
    ("all",      0.0,  0.35),   # every object the renderer can see: the "perfect label" extreme
    ("min15",   15.0,  0.35),
    ("min23",   23.4,  0.35),   # current: the real annotations' 5th percentile
    ("min35",   35.0,  0.35),   # only clearly visible objects
    ("min45",   45.0,  0.35),   # only large, unambiguous objects
    ("trunc10", 23.4,  0.10),   # keep heavily truncated edge boxes
    ("trunc60", 23.4,  0.60),   # drop them aggressively
]
report = {}
for name, minbox, minvis in VARIANTS:
    out = f"synthetic_lab_{name}"
    os.system(f"rm -rf {out}")
    written = []
    for i, img in enumerate(sorted(glob.glob(os.path.join(DEV, "*_RGB.jpeg")))):
        stem = os.path.basename(img).replace("camA_", "").replace("_RGB.jpeg", "")
        label = os.path.join(RAW, stem + "_bbox.txt")
        rover = os.path.join(RAW, "camA_" + stem + "_rover.txt")
        if not os.path.exists(label):
            continue
        written += tile_frame(img, label, out, n_tiles=15, seed=4000 + i,
                              rover_mask_path=rover if os.path.exists(rover) else None,
                              min_box_px=minbox, min_visible=minvis)
    box = np.array([t[2] for t in written])
    report[name] = dict(min_box_px=minbox, min_visible=minvis, tiles=len(written),
                        boxes=int(box.sum()), boxes_per_tile=float(box.mean()))
    print(f"{name:9s} min_box {minbox:5.1f} min_vis {minvis:.2f} -> {len(written)} tiles, "
          f"{int(box.sum()):5d} boxes, {box.mean():5.2f}/tile", flush=True)
json.dump(report, open("audit/label_variants.json", "w"), indent=1)
print("REAL reference: 7.57 boxes/tile")
print("VARIANTS COMPLETE")
