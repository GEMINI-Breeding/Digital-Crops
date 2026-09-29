#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=220G
#SBATCH --gres=gpu:1
#SBATCH -J s2r_vfloor
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/vfloor-%j.out
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
unset DISPLAY
env/bin/python - <<'PY'
import glob, json, os, subprocess, sys
import numpy as np, cv2
sys.path.insert(0, os.path.abspath("."))
from syn2real.tile import tile_frame
from syn2real import camera_pipeline as cp
from syn2real.leafcolour import WINDOW_PX, A_FOLIAGE, MIN_FOLIAGE_FRACTION, summarise

BASE = json.load(open("audit/phase5_confirm.json"))["results"]["18"]["overrides"]

def build(floor, tag):
    raw, dev, tiles = f"vf_raw_{tag}", f"vf_dev_{tag}", f"vf_tiles_{tag}"
    for d in (raw, dev, tiles): os.system(f"rm -rf {d}")
    ov = dict(BASE); ov["leaf.minimum_N_area"] = f"{floor:.2f}"
    flat = [x for kv in ov.items() for x in kv]
    for seed in (9000, 9001, 9002):
        r = subprocess.run(["./SyntheticAutotuning","render","../config/baseline.cfg",str(seed),
                            "camera.samples","50","output.folder",f"../{raw}/"]+flat,
                           capture_output=True, text=True, cwd="build-gpu")
        if r.returncode != 0:
            raise SystemExit(f"render failed: {(r.stderr.strip().splitlines() or ['?'])[-1]}")
    subprocess.run(["env/bin/python","scripts/develop.py",raw,"--out",dev,"--gain",str(cp.DEVELOP_GAIN)],
                   check=True, capture_output=True)
    for i, img in enumerate(sorted(glob.glob(os.path.join(dev,"*_RGB.jpeg")))):
        stem = os.path.basename(img).replace("camA_","").replace("_RGB.jpeg","")
        lab = os.path.join(raw, stem + "_bbox.txt")
        if not os.path.exists(lab): continue
        tile_frame(img, lab, tiles, n_tiles=15, seed=7000+i,
                   rover_mask_path=os.path.join(raw,"camA_"+stem+"_rover.txt"),
                   ground_mask_path=os.path.join(raw,"camA_"+stem+"_ground.txt"))
    return tiles

def hue_stats(tiles):
    L_, h_ = [], []
    for f in sorted(glob.glob(os.path.join(tiles,"images","*.jpeg"))):
        lab = cv2.cvtColor(cv2.imread(f), cv2.COLOR_BGR2LAB).astype(np.float32)
        L, A, B = lab[:,:,0]*100/255, lab[:,:,1]-128, lab[:,:,2]-128
        fol = A < A_FOLIAGE
        for y in range(0, L.shape[0]-WINDOW_PX+1, WINDOW_PX):
            for x in range(0, L.shape[1]-WINDOW_PX+1, WINDOW_PX):
                m = fol[y:y+WINDOW_PX, x:x+WINDOW_PX]
                if m.mean() < MIN_FOLIAGE_FRACTION: continue
                L_.append(L[y:y+WINDOW_PX,x:x+WINDOW_PX][m].mean())
                a = A[y:y+WINDOW_PX,x:x+WINDOW_PX][m].mean()
                b = B[y:y+WINDOW_PX,x:x+WINDOW_PX][m].mean()
                h_.append(np.degrees(np.arctan2(b,a)))
    L_, h_ = np.array(L_), np.array(h_)
    med = np.median(L_)
    pale = L_ > med + 4
    return dict(hue_med=float(np.median(h_)), hue_spread=float(np.percentile(h_,90)-np.percentile(h_,10)),
                hue_pale=float(np.median(h_[pale])) if pale.sum()>5 else float('nan'),
                pale_frac=float(pale.mean()), corr=float(np.corrcoef(L_,h_)[0,1]))

print(f"{'floor':>7} {'hue med':>8} {'hue pale':>9} {'hue spread':>11} {'pale %':>8} "
      f"{'corr(L,hue)':>12} {'a* spread':>10} {'L* spread':>10}", flush=True)
for floor in (0.8, 2.0):
    t = build(floor, f"f{floor:.1f}")
    h = hue_stats(t); lc = summarise(t)
    print(f"{floor:7.1f} {h['hue_med']:8.1f} {h['hue_pale']:9.1f} {h['hue_spread']:11.2f} "
          f"{h['pale_frac']*100:8.1f} {h['corr']:12.3f} {lc['a_spread']:10.2f} "
          f"{lc['L_spread_within_tile']:10.2f}", flush=True)
    os.system(f"rm -rf vf_raw_f{floor:.1f} vf_dev_f{floor:.1f} vf_tiles_f{floor:.1f}")
print(f"{'REAL':>7} {123.5:8.1f} {123.1:9.1f} {6.34:11.2f} {31.7:8.1f} {-0.154:12.3f} "
      f"{8.73:10.2f} {15.78:10.2f}")
print("VERIFY FLOOR COMPLETE")
PY
