"""Where does the leaf chroma variation disappear?

Established so far: the nitrogen model builds a Cab spread of 64.4, 61% of it survives to visible
pixels (39.2), and flat-leaf optics through this camera say a spread that size is worth 5-6 units of
a*. The rendered tiles show 4.25 against a control of 4.25 -- nothing. Something between the visible
pigment and the measured tile removes all of it.

This measures a* spread after every stage of the chain, on one frame, so the loss can be located
rather than guessed:

  raw -> exposure -> colour matrix -> tone curve -> sRGB -> 2x tile downsample -> JPEG

and at two granularities: per pixel, and per 55-tile-px window (what the leaf-colour metric uses).
If the spread is alive per-pixel and dead per-window, the metric is averaging it away and the model
is fine. If it dies at a named stage, that stage is the culprit. If it is never there at all, the
in-canopy illumination is swamping the pigment differences and flat-leaf optics were misleading.

The pigment correlation is the control: if per-pixel a* does not track per-pixel chlorophyll, no
amount of chain analysis matters because the signal never reached the sensor.
"""
import glob, json, os, subprocess, sys
import numpy as np
import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real import camera_pipeline as cp
from syn2real.leafcolour import WINDOW_PX, A_FOLIAGE, MIN_FOLIAGE_FRACTION, REAL

SEED = 5200
GAIN = cp.DEVELOP_GAIN
CAB_PER_N = 100.0 * 0.50 * 0.40
RAW = "chroma_raw"
BASE = json.load(open("audit/phase5_confirm.json"))["results"]["18"]["overrides"]
SETTING = {"leaf.nitrogen_model": "1", "leaf.target_N_area": "4.2",
           "leaf.max_N_accumulation_rate": "0.140", "leaf.nitrogen_supply_gN": "8.0"}

os.system(f"rm -rf {RAW}")
ov = dict(BASE); ov.update(SETTING)
flat = [x for kv in ov.items() for x in kv]
r = subprocess.run(["./SyntheticAutotuning", "render", "../config/baseline.cfg", str(SEED),
                    "camera.samples", "50", "output.folder", f"../{RAW}/"] + flat,
                   capture_output=True, text=True, cwd="build-gpu")
if r.returncode != 0:
    raise SystemExit(f"render failed: {(r.stderr.strip().splitlines() or ['no stderr'])[-1]}")

exr = sorted(glob.glob(os.path.join(RAW, "*_raw.exr")))[0]
nmap = sorted(glob.glob(os.path.join(RAW, "*_leafN.txt")))[0]
gmap = sorted(glob.glob(os.path.join(RAW, "*_ground.txt")))[0]
raw = cp.read_raw_exr(exr)
leafN = np.loadtxt(nmap)
ground = np.loadtxt(gmap)
ground = np.isfinite(ground) & (ground > 0)
leaf = np.isfinite(leafN) & (leafN > 0) & (~ground)
print(f"frame {raw.shape}, leaf pixels {leaf.sum()}, Cab visible spread "
      f"{(np.percentile(leafN[leaf],90)-np.percentile(leafN[leaf],10))*CAB_PER_N:.1f}\n")

ccm = cp.read_ccm("calib/ccm_camA_20230728.xml")


def lab_of(disp_rgb01):
    bgr = np.clip(disp_rgb01[:, :, ::-1] * 255, 0, 255).astype(np.uint8)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    return lab[:, :, 0] * 100 / 255, lab[:, :, 1] - 128


def report(name, L, A, mask, cab=None):
    a = A[mask]
    spread = float(np.percentile(a, 90) - np.percentile(a, 10))
    line = f"  {name:34s} a* p10 {np.percentile(a,10):7.2f}  p50 {np.median(a):7.2f}  " \
           f"p90 {np.percentile(a,90):7.2f}  spread {spread:6.2f}"
    if cab is not None:
        line += f"   corr(a*,Cab) {np.corrcoef(cab[mask], a)[0,1]:+.3f}"
    print(line, flush=True)
    return spread


cab_full = leafN * CAB_PER_N
print("PER PIXEL, through the chain:")
# Mirrors camera_pipeline.process() stage for stage, in its order. An earlier version of this script
# hand-rolled the chain and left out white balance -- a per-channel gain of 1.563/1.000/1.596 applied
# BEFORE the colour matrix -- which put median a* at -40 instead of the -20 the real pipeline
# produces, and made every number here describe an image the project never renders.
stages = {}
x1 = cp.white_balance(raw * GAIN, cp.DEFAULTS["white_balance"])
stages["1 exposure + white balance"] = cp.lin_to_srgb(x1)
x2 = cp.apply_ccm(x1, ccm, strength=1.0)
stages["2 + colour matrix"] = cp.lin_to_srgb(x2)
x3 = cp.tone_curve(x2, black_level=0.0, highlight_knee=0.55)
x3 = cp.adjust_saturation(x3, cp.DEFAULTS["saturation"])
stages["3 + tone curve (full develop)"] = cp.lin_to_srgb(x3)
for name, disp in stages.items():
    L, A = lab_of(disp)
    report(name, L, A, leaf, cab_full)

full = cp.lin_to_srgb(x3).astype(np.float32)

# Cross-check against what develop.py actually writes, so a silent divergence like the missing white
# balance cannot go unnoticed a second time.
reference = cp.process(raw, exposure=GAIN, ccm="calib/ccm_camA_20230728.xml",
                       ccm_strength=1.0, highlight_knee=0.55)
delta = float(np.abs(reference - full).mean() * 255)
print(f"  [chain check: {delta:.3f}/255 mean difference from camera_pipeline.process()]", flush=True)
if delta > 1.0:
    raise SystemExit(f"staged chain diverges from process() by {delta:.2f}/255; the stages above do "
                     "not describe the real pipeline")

# 4. tile scale: cut 1280 native -> 640, a 2x area average
h, w = full.shape[:2]
small = cv2.resize(full, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
leaf_s = cv2.resize(leaf.astype(np.float32), (w // 2, h // 2), interpolation=cv2.INTER_AREA) > 0.9
cab_s = cv2.resize(cab_full.astype(np.float32), (w // 2, h // 2), interpolation=cv2.INTER_AREA)
L4, A4 = lab_of(small)
report("4 + 2x downsample to tile scale", L4, A4, leaf_s, cab_s)

# 5. JPEG, at the quality the tiles are written with (chroma subsampling lives here)
ok, buf = cv2.imencode(".jpeg", np.clip(small[:, :, ::-1] * 255, 0, 255).astype(np.uint8),
                       [int(cv2.IMWRITE_JPEG_QUALITY), 92])
dec = cv2.imdecode(buf, cv2.IMREAD_COLOR).astype(np.float32) / 255.0
L5, A5 = lab_of(dec[:, :, ::-1])
jpeg_spread = report("5 + JPEG encode", L5, A5, leaf_s, cab_s)

# The metric's own granularity, on the final image.
print(f"\nPER {WINDOW_PX}-px WINDOW (what syn2real.leafcolour measures):")
foliage = A5 < A_FOLIAGE
win_a = []
for y in range(0, A5.shape[0] - WINDOW_PX + 1, WINDOW_PX):
    for x_ in range(0, A5.shape[1] - WINDOW_PX + 1, WINDOW_PX):
        m = foliage[y:y+WINDOW_PX, x_:x_+WINDOW_PX]
        if m.mean() < MIN_FOLIAGE_FRACTION:
            continue
        win_a.append(A5[y:y+WINDOW_PX, x_:x_+WINDOW_PX][m].mean())
win_a = np.array(win_a)
win_spread = float(np.percentile(win_a, 90) - np.percentile(win_a, 10))
print(f"  {len(win_a)} windows   a* p10 {np.percentile(win_a,10):7.2f}  "
      f"p50 {np.median(win_a):7.2f}  p90 {np.percentile(win_a,90):7.2f}  spread {win_spread:6.2f}")
print(f"\n  per-pixel spread at the same stage: {jpeg_spread:.2f}")
print(f"  window averaging retains {win_spread/max(jpeg_spread,1e-6)*100:.0f}% of it")
print(f"  real canopy, same window metric:    {REAL['a_spread']:.2f}")

os.system(f"rm -rf {RAW}")
print("\nCHROMA STAGES COMPLETE")
