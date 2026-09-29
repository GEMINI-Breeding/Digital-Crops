"""Apparent leaf size by segmentation, as a check on the indirect measures.

Two indirect measures disagree with the visual impression and with each other:

  granulometry           synthetic structure radius 37.8 vs real 38.7 -- but it sizes BRIGHT
                         structures, and adjacent leaves of similar brightness merge into one.
  edge-bounded regions   synthetic MEDIAN region larger than real at every threshold -- but real
                         imagery carries more fine texture (noise 2.27 vs 1.92, edge sharpness 2.55
                         vs 2.00), which fragments real leaves more than synthetic ones.

Both are confounded by things that are not leaf size. Segmentation is not: it proposes object masks
and each mask is one thing. The identical model, prompts and filters run on both domains, so a
difference in the resulting size distribution is a difference in apparent leaf size.

Filters are stated rather than tuned: a mask counts as a leaf candidate if it is mostly vegetation,
compact enough to be a leaf rather than a canopy fragment, and not touching the tile border (a
clipped leaf measures smaller than it is, and clipping rates differ between the sets).
"""
import glob, json, os, sys
import numpy as np, cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

A_FOLIAGE = -12.0
MIN_VEG_FRACTION = 0.75      # mask must be mostly foliage
MIN_SOLIDITY = 0.80          # area / convex-hull area; leaves are convex-ish, canopy gaps are not
MIN_AREA_PX = 60             # below this is texture, not a leaf
MAX_AREA_FRAC = 0.25         # above this is a canopy region, not a leaf
N_TILES = 80


def leaf_masks(model, path):
    bgr = cv2.imread(path)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    veg = (lab[:, :, 1] - 128) < A_FOLIAGE
    if veg.mean() < 0.25:
        return []
    res = model(path, verbose=False, device=0)
    if not res or res[0].masks is None:
        return []
    out = []
    H, W = veg.shape
    for m in res[0].masks.data.cpu().numpy():
        mask = m > 0.5
        if mask.shape != veg.shape:
            mask = cv2.resize(mask.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST) > 0
        area = int(mask.sum())
        if area < MIN_AREA_PX or area > MAX_AREA_FRAC * H * W:
            continue
        if veg[mask].mean() < MIN_VEG_FRACTION:
            continue
        ys, xs = np.nonzero(mask)
        if ys.min() == 0 or xs.min() == 0 or ys.max() == H - 1 or xs.max() == W - 1:
            continue                      # touches the border: clipped, and clipping rates differ
        cnt, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnt:
            continue
        c = max(cnt, key=cv2.contourArea)
        hull = cv2.convexHull(c)
        hull_area = cv2.contourArea(hull)
        if hull_area <= 0 or cv2.contourArea(c) / hull_area < MIN_SOLIDITY:
            continue
        if len(c) >= 5:
            (_cx, _cy), (ax1, ax2), _ang = cv2.fitEllipse(c)
            major, minor = max(ax1, ax2), min(ax1, ax2)
        else:
            major = minor = float(np.sqrt(area))
        out.append((float(np.sqrt(area)), float(major), float(minor)))
    return out


def summarise(model, label, files, seed=0):
    rng = np.random.default_rng(seed)
    if len(files) > N_TILES:
        files = [files[i] for i in rng.choice(len(files), N_TILES, replace=False)]
    rows = []
    for f in files:
        rows += leaf_masks(model, f)
    if not rows:
        raise SystemExit(f"no leaf candidates in {label}")
    a = np.array(rows)
    per_tile = len(rows) / len(files)
    print(f"{label:28s} {len(rows):6d} leaves ({per_tile:5.1f}/tile)  "
          f"sqrt(area) p50 {np.median(a[:,0]):5.1f}  major p50 {np.median(a[:,1]):5.1f} "
          f"p90 {np.percentile(a[:,1],90):5.1f}  minor p50 {np.median(a[:,2]):5.1f}", flush=True)
    return dict(n=len(rows), per_tile=per_tile, sqrt_area_p50=float(np.median(a[:, 0])),
                major_p50=float(np.median(a[:, 1])), major_p90=float(np.percentile(a[:, 1], 90)),
                minor_p50=float(np.median(a[:, 2])))


# Guarded: leaf_masks() is imported by scripts/leaf_density_joint.py, and without this the whole
# measurement re-runs on import -- which it did once, costing several minutes and overwriting the
# result file with a duplicate run.
if __name__ == "__main__":
  os.environ.pop("YOLO_OFFLINE", None); os.environ.pop("ULTRALYTICS_OFFLINE", None)
  from ultralytics import SAM
  model = SAM("weights/mobile_sam.pt")
  print(f"filters: veg>{MIN_VEG_FRACTION}, solidity>{MIN_SOLIDITY}, "
        f"{MIN_AREA_PX}px<area<{MAX_AREA_FRAC:.0%} of tile, border-touching excluded\n")
  real = summarise(model, "REAL", sorted(glob.glob("real/images/*.jpg") + glob.glob("real/images/*.jpeg")))
  syn = summarise(model, "SYNTHETIC (current build)", sorted(glob.glob("synthetic_cur/images/*.jpeg")))
  json.dump(dict(real=real, synthetic=syn), open("audit/sam_leaf_size.json", "w"), indent=1)
  print(f"\nreal/synthetic major-axis ratio: {real['major_p50']/syn['major_p50']:.2f}x")
  print(f"leaves found per tile: real {real['per_tile']:.1f}, synthetic {syn['per_tile']:.1f}")
  print("\nfor reference: granulometry ratio 1.02x, edge-region ratio 0.78x (both confounded)")
  print("SAM LEAF SIZE COMPLETE")
