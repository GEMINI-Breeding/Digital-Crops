"""Hand-labelled leaflet midribs vs SAM masks, in the same 256 px windows.

The hand labels are the first direct measurement of real leaf length; every earlier real number
came from SAM or from granulometry.  They are not a complete inventory -- the labeller only drew a
line where the midrib was clearly visible -- so this does not measure SAM recall over all leaves.
What it does measure, like for like:

  size    fully-visible hand-labelled leaflets vs SAM masks lying wholly inside the same window
  bias    for the SAM masks a human confirmed (label midpoint inside the mask), SAM length / hand
          length -- the per-object bias, free of any difference in which objects each set contains
  extras  SAM masks in the window that no hand label lands in -- the population suspected of
          dragging the real median down

Windows are 256 px crops of 640 px tiles; SAM runs on the whole tile, as it does in the pipeline.
"""
import json, os, sys
import numpy as np, cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.sam_leaf_size import (A_FOLIAGE, MIN_VEG_FRACTION, MIN_SOLIDITY,
                                   MIN_AREA_PX, MAX_AREA_FRAC)

CROP_DIR = "/group/bnbaileygrp/bnbailey/Downloads/leaf_labels"
LABELS = os.environ["SP"] + "/handlabels.json"


def tile_masks(model, path):
    """Every mask passing the pipeline's leaf filters, with its geometry kept."""
    bgr = cv2.imread(path)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    veg = (lab[:, :, 1] - 128) < A_FOLIAGE
    res = model(path, verbose=False, device=DEVICE)
    H, W = veg.shape
    out = []
    for m in res[0].masks.data.cpu().numpy():
        mask = m > 0.5
        if mask.shape != veg.shape:
            mask = cv2.resize(mask.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST) > 0
        area = int(mask.sum())
        if area < MIN_AREA_PX or area > MAX_AREA_FRAC * H * W:
            continue
        if veg[mask].mean() < MIN_VEG_FRACTION:
            continue
        cnt, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnt:
            continue
        c = max(cnt, key=cv2.contourArea)
        hull_area = cv2.contourArea(cv2.convexHull(c))
        if hull_area <= 0 or cv2.contourArea(c) / hull_area < MIN_SOLIDITY:
            continue
        ys, xs = np.nonzero(mask)
        if len(c) >= 5:
            _, (a1, a2), _ = cv2.fitEllipse(c)
            major, minor = max(a1, a2), min(a1, a2)
        else:
            major = minor = float(np.sqrt(area))
        out.append(dict(mask=mask, area=area, major=float(major), minor=float(minor),
                        x0=int(xs.min()), x1=int(xs.max()), y0=int(ys.min()), y1=int(ys.max()),
                        tile_border=bool(ys.min() == 0 or xs.min() == 0
                                         or ys.max() == H - 1 or xs.max() == W - 1)))
    return out


def pct(a, label, extra=""):
    a = np.asarray(a, float)
    if a.size == 0:
        print(f"{label:34s} n=   0")
        return
    print(f"{label:34s} n={a.size:4d}  p25 {np.percentile(a,25):6.1f}  p50 {np.median(a):6.1f}  "
          f"p75 {np.percentile(a,75):6.1f}  p90 {np.percentile(a,90):6.1f} {extra}")


if __name__ == "__main__":
    os.environ.pop("YOLO_OFFLINE", None); os.environ.pop("ULTRALYTICS_OFFLINE", None)
    import torch
    DEVICE = 0 if torch.cuda.is_available() else "cpu"
    from ultralytics import SAM
    model = SAM("weights/mobile_sam.pt")

    manifest = {r["file"]: r for r in json.load(open(f"{CROP_DIR}/manifest.json"))}
    labels = json.load(open(LABELS))
    cache = {}

    hand_whole, hand_part = [], []
    sam_in_window, sam_matched, sam_extra = [], [], []
    ratios = []
    n_label_hit = n_label_miss = 0

    for fname, lines in sorted(labels.items()):
        rec = manifest[fname]
        src = "real/images/" + rec["source"]
        if src not in cache:
            cache[src] = tile_masks(model, src)
        X, Y, S = rec["x"], rec["y"], rec["size"]

        whole = [l for l in lines if not l["occluded"]]
        hand_whole += [np.hypot(l["x2"]-l["x1"], l["y2"]-l["y1"]) for l in whole]
        hand_part += [np.hypot(l["x2"]-l["x1"], l["y2"]-l["y1"])
                      for l in lines if l["occluded"]]

        # SAM masks lying wholly inside this window
        inside = [m for m in cache[src]
                  if m["x0"] >= X and m["x1"] < X + S and m["y0"] >= Y and m["y1"] < Y + S]
        sam_in_window += [m["major"] for m in inside]

        # any mask on the tile may host a label; a label near the window edge can belong to a
        # mask that spills out of it, and excluding those would fake a miss
        hit = set()
        for l in whole:
            mx = int(round((l["x1"] + l["x2"]) / 2)) + X
            my = int(round((l["y1"] + l["y2"]) / 2)) + Y
            cand = [m for m in cache[src] if m["mask"][my, mx]]
            if not cand:
                n_label_miss += 1
                continue
            m = min(cand, key=lambda m: m["area"])       # innermost mask at that point
            n_label_hit += 1
            hit.add(id(m))
            hand_len = np.hypot(l["x2"]-l["x1"], l["y2"]-l["y1"])
            sam_matched.append(m["major"])
            ratios.append(m["major"] / hand_len)
        sam_extra += [m["major"] for m in inside if id(m) not in hit]

    print(f"\ntiles {len(cache)}   windows {len(labels)}   "
          f"SAM masks passing filters, whole tiles: {sum(len(v) for v in cache.values())}\n")
    pct(hand_whole, "hand: fully-visible leaflets")
    pct(hand_part,  "hand: partial / edge-cut")
    print()
    pct(sam_in_window, "SAM: masks wholly inside window")
    pct(sam_matched,   "SAM: masks a hand label lands in")
    pct(sam_extra,     "SAM: in-window, no hand label")
    print()
    r = np.array(ratios)
    print(f"per-object bias  SAM major / hand midrib length:  "
          f"p25 {np.percentile(r,25):.2f}  median {np.median(r):.2f}  p75 {np.percentile(r,75):.2f}")
    print(f"hand-labelled fully-visible leaflets SAM found: {n_label_hit}/{n_label_hit+n_label_miss}"
          f" ({n_label_hit/(n_label_hit+n_label_miss):.0%});  missed {n_label_miss}")
    json.dump(dict(hand_whole=hand_whole, hand_part=hand_part, sam_in_window=sam_in_window,
                   sam_matched=sam_matched, sam_extra=sam_extra, ratios=ratios,
                   n_hit=n_label_hit, n_miss=n_label_miss),
              open("audit/handlabel_vs_sam.json", "w"), indent=1)
    print("\nHANDLABEL VS SAM COMPLETE")
