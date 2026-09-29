"""Audit SAM against exact per-leaf masks. Synthetic only, where truth is known.

Every leaf-size conclusion so far rests on SAM, and SAM was only ever checked against aggregate
bounding-box statistics -- which cannot distinguish a mask that is one leaf from one that is half a
leaf or three leaves. This matches masks to ground truth object by object and measures what SAM
actually returns:

  recall        fraction of visible truth leaves that SAM finds at all
  size bias     for MATCHED pairs, SAM's major axis over truth's -- the calibration factor that
                every cross-domain ratio quoted so far has implicitly assumed to be 1.0
  split rate    truth leaves covered by two or more SAM masks (the hypothesis under test)
  merge rate    SAM masks spanning two or more truth leaves

A truth leaf counts as visible if it holds at least MIN_TRUTH_PX pixels in the tile, so leaves
occluded to a sliver are not scored as missed detections.
"""
import glob, json, os, subprocess, sys
from collections import defaultdict

import numpy as np, cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real import camera_pipeline as cp
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sam_leaf_size import (A_FOLIAGE, MIN_VEG_FRACTION, MIN_SOLIDITY, MIN_AREA_PX, MAX_AREA_FRAC)

SEED = 9950
MIN_TRUTH_PX = 200          # a truth leaf smaller than this in-tile is too occluded to expect
IOU_MATCH = 0.30
BASE = json.load(open("audit/phase5_confirm.json"))["results"]["18"]["overrides"]
RAW = "sma_raw"

os.system(f"rm -rf {RAW}")
ov = dict(BASE)
ov.update({"canopy.germination_fraction_min": "0.35", "canopy.germination_fraction_max": "0.85",
           "output.write_leaf_ids": "1"})
flat = [x for kv in ov.items() for x in kv]
r = subprocess.run(["./SyntheticAutotuning", "render", "../config/baseline.cfg", str(SEED),
                    "camera.samples", "50", "output.folder", f"../{RAW}/"] + flat,
                   capture_output=True, text=True, cwd="build-gpu")
if r.returncode != 0:
    raise SystemExit(f"render failed: {(r.stderr.strip().splitlines() or ['?'])[-1]}")
print(next((l for l in r.stdout.splitlines() if "DIAG leaf_object_ids" in l), "no id diag"), flush=True)

subprocess.run(["env/bin/python", "scripts/develop.py", RAW, "--out", "sma_dev",
                "--target-L", str(cp.REAL_FOLIAGE_L)], check=True, capture_output=True)
dev = sorted(glob.glob("sma_dev/*_RGB.jpeg"))[0]
stem = os.path.basename(dev).replace("camA_", "").replace("_RGB.jpeg", "")
idmap = np.loadtxt(os.path.join(RAW, "camA_" + stem + "_leafid.txt"))
rgb = cv2.imread(dev)
print(f"frame {rgb.shape[:2]}, id map {idmap.shape}, distinct visible leaves "
      f"{len(set(np.unique(idmap[np.isfinite(idmap) & (idmap > 0)]).tolist()))}", flush=True)

os.environ.pop("YOLO_OFFLINE", None); os.environ.pop("ULTRALYTICS_OFFLINE", None)
from ultralytics import SAM
sam = SAM("weights/mobile_sam.pt")

# Cut tiles the same way the dataset does, and carry the id map through the identical crop so truth
# and image stay registered.
TILE_NATIVE, TILE = 1280, 640
H, W = rgb.shape[:2]
rng = np.random.default_rng(0)
recalls, biases, splits, merges, n_truth_all = [], [], 0, 0, 0
for _ in range(8):
    x = int(rng.integers(0, W - TILE_NATIVE)); y = int(rng.integers(0, H - TILE_NATIVE))
    crop = cv2.resize(rgb[y:y+TILE_NATIVE, x:x+TILE_NATIVE], (TILE, TILE), interpolation=cv2.INTER_AREA)
    ids = cv2.resize(idmap[y:y+TILE_NATIVE, x:x+TILE_NATIVE], (TILE, TILE), interpolation=cv2.INTER_NEAREST)
    truth = {}
    for lid in np.unique(ids):
        if not np.isfinite(lid) or lid <= 0:
            continue
        m = ids == lid
        if m.sum() < MIN_TRUTH_PX:
            continue
        truth[int(lid)] = m
    if not truth:
        continue
    tmp = "sma_tile.jpeg"; cv2.imwrite(tmp, crop, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    res = sam(tmp, verbose=False, device=0)
    masks = []
    if res and res[0].masks is not None:
        lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB).astype(np.float32)
        veg = (lab[:, :, 1] - 128) < A_FOLIAGE
        for mm in res[0].masks.data.cpu().numpy():
            m = mm > 0.5
            if m.shape != veg.shape:
                m = cv2.resize(m.astype(np.uint8), (TILE, TILE), interpolation=cv2.INTER_NEAREST) > 0
            a = int(m.sum())
            if a < MIN_AREA_PX or a > MAX_AREA_FRAC * TILE * TILE:
                continue
            if veg[m].mean() < MIN_VEG_FRACTION:
                continue
            masks.append(m)
    # match
    hit = defaultdict(list)
    for si, sm in enumerate(masks):
        best, best_iou = None, 0.0
        for tid, tm in truth.items():
            inter = np.logical_and(sm, tm).sum()
            if inter == 0:
                continue
            iou = inter / np.logical_or(sm, tm).sum()
            if iou > best_iou:
                best, best_iou = tid, iou
        if best is not None and best_iou >= IOU_MATCH:
            hit[best].append(si)
    n_truth_all += len(truth)
    recalls.append(len(hit) / len(truth))
    for tid, sis in hit.items():
        if len(sis) > 1:
            splits += 1
        tm = truth[tid]
        cnt, _ = cv2.findContours(tm.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        c = max(cnt, key=cv2.contourArea)
        t_major = max(cv2.fitEllipse(c)[1]) if len(c) >= 5 else np.sqrt(tm.sum())
        sm = masks[sis[0]]
        cnt2, _ = cv2.findContours(sm.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        c2 = max(cnt2, key=cv2.contourArea)
        s_major = max(cv2.fitEllipse(c2)[1]) if len(c2) >= 5 else np.sqrt(sm.sum())
        if t_major > 0:
            biases.append(s_major / t_major)
    for si, sm in enumerate(masks):
        covered = sum(1 for tid, tm in truth.items()
                      if np.logical_and(sm, tm).sum() > 0.4 * tm.sum())
        if covered > 1:
            merges += 1
    os.remove(tmp)

print(f"\ntruth leaves scored: {n_truth_all}  (>= {MIN_TRUTH_PX}px in tile)")
print(f"recall              : {np.mean(recalls)*100:5.1f}%  of visible truth leaves matched at IoU>={IOU_MATCH}")
print(f"SIZE BIAS           : {np.median(biases):5.2f}x  SAM major / truth major, matched pairs "
      f"(n={len(biases)})")
print(f"split rate          : {splits/max(sum(len(r) for r in [recalls]),1):5.1f} truth leaves with >1 SAM mask "
      f"(count {splits})")
print(f"merge count         : {merges} SAM masks spanning >1 truth leaf")
print(f"\nEvery cross-domain ratio quoted so far assumed a size bias of 1.00.")
json.dump(dict(recall=float(np.mean(recalls)), size_bias=float(np.median(biases)),
               splits=int(splits), merges=int(merges), n_truth=int(n_truth_all)),
          open("audit/sam_mask_audit.json", "w"), indent=1)
os.system(f"rm -rf {RAW} sma_dev")
print("SAM MASK AUDIT COMPLETE")
