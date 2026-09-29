"""Mask overlays for real, trial 18, and the corrected architecture — all correctly exposed.

The overlay currently in the report compares real against an intermediate that was rendered before
the exposure fix (foliage L* 62.6 against a real 49.8). This renders the two configurations that
actually matter, each with its own exposure calibration, so the visual comparison is against builds
this project recommends rather than an accident of what was on disk.
"""
import glob, json, os, subprocess, sys
import numpy as np, cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from syn2real import camera_pipeline as cp
from syn2real.tile import tile_frame
from sam_leaf_size import (leaf_masks, A_FOLIAGE, MIN_VEG_FRACTION, MIN_SOLIDITY,
                           MIN_AREA_PX, MAX_AREA_FRAC)

TRIAL18 = json.load(open("audit/phase5_confirm.json"))["results"]["18"]["overrides"]
CORRECTED = dict(TRIAL18)
CORRECTED.update({"canopy.internode_length_max": "0.0750", "canopy.phyllochron": "6.00",
                  "canopy.max_nodes": "7", "leaf.prototype_scale_min": "0.1690",
                  "leaf.prototype_scale_max": "0.3040", "flower.bud_break_prob_min": "0.800",
                  "flower.bud_break_prob_max": "0.900", "flower.flowers_per_peduncle_min": "3",
                  "flower.flowers_per_peduncle_max": "3",
                  "canopy.germination_fraction_min": "0.4000",
                  "canopy.germination_fraction_max": "0.8000"})
SEEDS = (10500, 10501, 10502)

os.environ.pop("YOLO_OFFLINE", None); os.environ.pop("ULTRALYTICS_OFFLINE", None)
from ultralytics import SAM
sam = SAM("weights/mobile_sam.pt")


def render_tiles(ov, tag):
    raw, dev, tiles = f"lmp_raw_{tag}", f"lmp_dev_{tag}", f"lmp_tiles_{tag}"
    for d in (raw, dev, tiles):
        os.system(f"rm -rf {d}")
    flat = [x for kv in ov.items() for x in kv]
    for seed in SEEDS:
        r = subprocess.run(["./SyntheticAutotuning", "render", "../config/baseline.cfg", str(seed),
                            "camera.samples", "50", "output.folder", f"../{raw}/"] + flat,
                           capture_output=True, text=True, cwd="build-gpu")
        if r.returncode != 0:
            raise SystemExit(f"render failed ({tag}): {(r.stderr.strip().splitlines() or ['?'])[-1]}")
    subprocess.run(["env/bin/python", "scripts/develop.py", raw, "--out", dev,
                    "--target-L", str(cp.REAL_FOLIAGE_L)], check=True, capture_output=True)
    for i, img in enumerate(sorted(glob.glob(os.path.join(dev, "*_RGB.jpeg")))):
        stem = os.path.basename(img).replace("camA_", "").replace("_RGB.jpeg", "")
        lbl = os.path.join(raw, stem + "_bbox.txt")
        if not os.path.exists(lbl):
            continue
        tile_frame(img, lbl, tiles, n_tiles=15, seed=8300 + i,
                   rover_mask_path=os.path.join(raw, "camA_" + stem + "_rover.txt"),
                   ground_mask_path=os.path.join(raw, "camA_" + stem + "_ground.txt"))
    return raw, dev, tiles


def annotate(path):
    bgr = cv2.imread(path); out = bgr.copy()
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    veg = (lab[:, :, 1] - 128) < A_FOLIAGE
    res = sam(path, verbose=False, device=0)
    majors = []
    if res and res[0].masks is not None:
        H, W = veg.shape
        for mm in res[0].masks.data.cpu().numpy():
            m = mm > 0.5
            if m.shape != veg.shape:
                m = cv2.resize(m.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST) > 0
            a = int(m.sum())
            if a < MIN_AREA_PX or a > MAX_AREA_FRAC * H * W: continue
            if veg[m].mean() < MIN_VEG_FRACTION: continue
            ys, xs = np.nonzero(m)
            if ys.min() == 0 or xs.min() == 0 or ys.max() == H-1 or xs.max() == W-1: continue
            cnt, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not cnt: continue
            c = max(cnt, key=cv2.contourArea)
            hull = cv2.convexHull(c); ha = cv2.contourArea(hull)
            if ha <= 0 or cv2.contourArea(c)/ha < MIN_SOLIDITY or len(c) < 5: continue
            (ex, ey), (a1, a2), _ = cv2.fitEllipse(c)
            major = max(a1, a2); majors.append(major)
            cv2.drawContours(out, [c], -1, (0, 255, 255), 2)
            for col, th in (((0,0,0),3), ((0,255,255),1)):
                cv2.putText(out, f"{major:.0f}", (int(ex)-16, int(ey)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, th, cv2.LINE_AA)
    return out, majors


def panel(files, label, n=4, seed=3):
    rng = np.random.default_rng(seed)
    f = [files[i] for i in rng.choice(len(files), min(n, len(files)), replace=False)]
    tiles, allm = [], []
    for path in f:
        out, majors = annotate(path)
        allm += majors
        tiles.append(cv2.resize(out, (400, 400), interpolation=cv2.INTER_AREA))
    row = np.hstack(tiles)
    band = np.full((34, row.shape[1], 3), 30, np.uint8)
    med = float(np.median(allm)) if allm else float("nan")
    p90 = float(np.percentile(allm, 90)) if allm else float("nan")
    cv2.putText(band, f"{label}   median {med:.0f} px   p90 {p90:.0f} px   ({len(allm)} masks)",
                (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 1, cv2.LINE_AA)
    return np.vstack([band, row]), med, p90


rows = []
real = sorted(glob.glob("real/images/*.jpg") + glob.glob("real/images/*.jpeg"))
p, m, q = panel(real, "REAL"); rows.append(p)
print(f"REAL median {m:.1f} p90 {q:.1f}", flush=True)
for tag, ov, label in (("t18", TRIAL18, "SYNTHETIC - trial 18 (the shipped dataset)"),
                       ("cor", CORRECTED, "SYNTHETIC - corrected architecture (s18)")):
    raw, dev, tiles = render_tiles(ov, tag)
    fs = sorted(glob.glob(os.path.join(tiles, "images", "*.jpeg")))
    p, m, q = panel(fs, label); rows.append(p)
    print(f"{label}: median {m:.1f} p90 {q:.1f}", flush=True)
    for d in (raw, dev, tiles):
        os.system(f"rm -rf {d}")
cv2.imwrite("audit/leaf_mask_panels.png", np.vstack(rows))
print("wrote audit/leaf_mask_panels.png")
print("LEAF MASK PANELS COMPLETE")
