"""Re-render section 08's tile strip and section 09's diagnostic against the current build.

Both were generated on 30 August from the v18 build and have been stale since. Three changes have
altered the images themselves: soil.reflectance_scale 0.22, which took synthetic soil from L* 75.7
to 40.0; manual exposure with a fixed post-processing gain replacing whole-frame auto-exposure; and
exact ground-mask tile selection replacing the Excess Green classifier that cannot see this soil.
The geometry is trial 18's, the only configuration whose advantage survived re-measurement on fresh
draws.

Tile selection for the strip uses the EXACT per-tile cover returned by tile_frame, not the ExG
recomputation the old make_strip.py did. On this soil ExG reports near-total cover for every tile,
so ordering by it makes the 25th/50th/75th percentile picks arbitrary -- which is the same defect
the strip is being regenerated to stop illustrating.
"""
import base64, glob, json, os, subprocess, sys
import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real import camera_pipeline as cp
from syn2real.tile import tile_frame
from syn2real.leafcolour import summarise as leafcolour_summarise, REAL as LEAF_REAL

FRAMES = int(os.environ.get("REFRESH_FRAMES", "10"))
SCENE_SEED0 = 9000                      # neither the search's 7000 nor the confirmation's 8000
                                        # (held fixed across refreshes so successive strips
                                        #  differ only by the change under test)
SAMPLES = 50                            # what the training tiles are actually rendered at
GAIN = cp.DEVELOP_GAIN
RAW, DEV, TILES = "frames_cur", "frames_cur_dev", "synthetic_cur"

# The current best configuration, not trial 18: audit/best_config.json records what changed and
# why. Detection performance is unmeasured for it (section 17).
overrides = json.load(open("audit/best_config.json"))["overrides"]
print(f"trial 18 overrides: {json.dumps(overrides, indent=1)}", flush=True)

for d in (RAW, DEV, TILES):
    os.system(f"rm -rf {d}")

flat = [x for kv in overrides.items() for x in kv]
for i in range(FRAMES):
    r = subprocess.run(["./SyntheticAutotuning", "render", "../config/baseline.cfg",
                        str(SCENE_SEED0 + i), "camera.samples", str(SAMPLES),
                        "output.folder", f"../{RAW}/"] + flat,
                       capture_output=True, text=True, cwd="build-gpu")
    if r.returncode != 0:
        raise SystemExit(f"render {i} failed: {(r.stderr.strip().splitlines() or ['no stderr'])[-1]}")
    print(f"  rendered frame {i+1}/{FRAMES}", flush=True)

subprocess.run(["env/bin/python", "scripts/develop.py", RAW, "--out", DEV, "--target-L", str(cp.REAL_FOLIAGE_L)],
               check=True)

written = []
for i, img in enumerate(sorted(glob.glob(os.path.join(DEV, "*_RGB.jpeg")))):
    stem = os.path.basename(img).replace("camA_", "").replace("_RGB.jpeg", "")
    label = os.path.join(RAW, stem + "_bbox.txt")
    if not os.path.exists(label):
        print(f"  SKIP {stem}: no labels", flush=True)
        continue
    written += tile_frame(img, label, TILES, n_tiles=15, seed=SCENE_SEED0 - 2000 + i,
                          rover_mask_path=os.path.join(RAW, "camA_" + stem + "_rover.txt"),
                          ground_mask_path=os.path.join(RAW, "camA_" + stem + "_ground.txt"))
if len(written) < 40:
    raise SystemExit(f"only {len(written)} tiles written; the set is too small to report on")

cov = np.array([t[1] for t in written])
box = np.array([t[2] for t in written])
print(f"\n{len(written)} tiles, {int(box.sum())} boxes", flush=True)
print(f"exact cover  p5 {np.percentile(cov,5):.3f}  p50 {np.median(cov):.3f}  p95 {np.percentile(cov,95):.3f}"
      f"   (real 0.568 / 0.947 / 0.984)", flush=True)
print(f"boxes/tile   mean {box.mean():.2f}   (real 7.57)", flush=True)

# --- leaf-to-leaf colour variation ------------------------------------------------------------
lc = leafcolour_summarise(TILES)
print(f"\nleaf-patch colour ({lc['n_windows']} windows):", flush=True)
print(f"  a*  p10 {lc['a_p10']:6.2f}  p50 {lc['a_p50']:6.2f}  p90 {lc['a_p90']:6.2f}  "
      f"spread {lc['a_spread']:5.2f}   (real {LEAF_REAL['a_spread']:.2f})", flush=True)
print(f"  L*  within-tile spread {lc['L_spread_within_tile']:5.2f}   "
      f"(real {LEAF_REAL['L_spread_within_tile']:.2f});  median L* {lc['L_p50']:5.2f} "
      f"(real {LEAF_REAL['L_p50']:.2f})", flush=True)

# --- section 08 strip, picked on exact cover -------------------------------------------------
order = sorted(zip(cov, [t[0] for t in written]))
picks = [order[int(q * (len(order) - 1))] for q in (0.25, 0.50, 0.75)]
panels = []
for c, name in picks:
    hits = glob.glob(os.path.join(TILES, "images", name + ".*"))
    if not hits:
        raise SystemExit(f"tile image for {name} not found under {TILES}/images")
    panels.append(cv2.resize(cv2.imread(hits[0]), (200, 200), interpolation=cv2.INTER_AREA))
    print(f"  strip pick cover={c:.3f}  {os.path.basename(hits[0])}", flush=True)
ok, buf = cv2.imencode(".jpg", np.hstack(panels), [int(cv2.IMWRITE_JPEG_QUALITY), 88])
if not ok:
    raise SystemExit("strip encode failed")
b64 = base64.b64encode(buf.tobytes()).decode("ascii")
open("audit/strip_current.b64", "w").write(b64)
print(f"wrote audit/strip_current.b64 ({len(b64)/1024:.0f} KB)", flush=True)

# --- section 09 diagnostic -------------------------------------------------------------------
from syn2real.report import build as build_report
df, _, _ = build_report(real_root="real", syn_root=TILES, outdir="audit")
os.replace("audit/gap_report.csv", "audit/gap_report_current.csv")
os.replace("audit/gap_distributions.png", "audit/gap_distributions_current.png")
print(f"\nwrote audit/gap_report_current.csv ({len(df)} statistics)", flush=True)
print(df.to_string(), flush=True)
print("REFRESH COMPLETE", flush=True)
