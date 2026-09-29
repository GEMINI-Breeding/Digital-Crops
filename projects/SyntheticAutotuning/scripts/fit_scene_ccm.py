"""Fit the colour matrix against scene content rather than a calibration board.

The board is a calibration artefact a new trial will not have, and it is the wrong reference for this
scene: its patches are matte paint, leaves are translucent, and fitting the board MORE faithfully
(root-polynomial, board RMS 59.7 -> 50.4) made the rendered scene worse. Unlabelled real imagery
always exists, and the renderer's exact masks make the synthetic side unambiguous.

Two statistics are deliberately EXCLUDED from the objective:

  foliage L*  -- set by the exposure gain, which is fitted separately. Including it would let the
                 matrix darken the image to score a colour improvement.
  soil L*     -- synthetic soil is ~7 L* too bright under every colour transform tried, which is a
                 soil reflectance error. A colour matrix asked to absorb it would distort foliage to
                 fix ground.

Both are still reported, as checks on a fit that never saw them.
"""
import glob, json, os, subprocess, sys
import numpy as np, cv2
from scipy.optimize import minimize

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real import camera_pipeline as cp
from syn2real import colorboard as cb

REAL = dict(fol_a=-21.0, fol_b=32.03, fol_hue=123.5, veg_sat=0.545,
            soil_a=2.0, soil_b=12.0, fol_L=47.84, soil_L=39.22)
SEEDS = (9100, 9101, 9102, 9103)
RAW = "sccm_raw"
SUB = 25
BASE = json.load(open("audit/phase5_confirm.json"))["results"]["18"]["overrides"]

os.system(f"rm -rf {RAW}")
flat = [x for kv in BASE.items() for x in kv]
for seed in SEEDS:
    r = subprocess.run(["./SyntheticAutotuning", "render", "../config/baseline.cfg", str(seed),
                        "camera.samples", "50", "output.folder", f"../{RAW}/"] + flat,
                       capture_output=True, text=True, cwd="build-gpu")
    if r.returncode != 0:
        raise SystemExit(f"render failed: {(r.stderr.strip().splitlines() or ['?'])[-1]}")
print(f"rendered {len(SEEDS)} frames with the current build", flush=True)

fol_px, soil_px = [], []
for exr in sorted(glob.glob(os.path.join(RAW, "*_raw.exr"))):
    raw = cp.read_raw_exr(exr)
    stem = os.path.basename(exr).replace("_raw.exr", "")
    g = np.loadtxt(os.path.join(RAW, stem + "_ground.txt"))
    ground = np.isfinite(g) & (g > 0)
    rov = os.path.join(RAW, stem + "_rover.txt")
    rover = np.zeros_like(ground)
    if os.path.exists(rov):
        rv = np.loadtxt(rov); rover = np.isfinite(rv) & (rv > 0)
    scene = ~rover
    fol_px.append(raw[scene & ~ground][::SUB]); soil_px.append(raw[scene & ground][::SUB])
fol = np.concatenate(fol_px).astype(np.float32)
soil = np.concatenate(soil_px).astype(np.float32)
print(f"foliage pixels {len(fol)}, soil pixels {len(soil)}\n", flush=True)


def develop(px, mat, gain):
    x = cp.white_balance(px[None] * gain, cp.DEFAULTS["white_balance"])
    x = np.maximum(x @ mat.T, 0.0)
    x = cp.tone_curve(x, black_level=0.0, highlight_knee=0.55)
    srgb = cp.lin_to_srgb(x)
    bgr = np.clip(srgb[:, :, ::-1] * 255, 0, 255).astype(np.uint8)
    return (cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32),
            cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV).astype(np.float32))


def stats(mat, gain):
    lab, hsv = develop(fol, mat, gain)
    a, b = float(np.median(lab[0, :, 1] - 128)), float(np.median(lab[0, :, 2] - 128))
    out = dict(fol_L=float(np.median(lab[0, :, 0]) * 100 / 255), fol_a=a, fol_b=b,
               fol_hue=float(np.degrees(np.arctan2(b, a))),
               veg_sat=float(np.median(hsv[0, :, 1]) / 255))
    lab_s, _ = develop(soil, mat, gain)
    out.update(soil_L=float(np.median(lab_s[0, :, 0]) * 100 / 255),
               soil_a=float(np.median(lab_s[0, :, 1] - 128)),
               soil_b=float(np.median(lab_s[0, :, 2] - 128)))
    return out


def fit_gain(mat):
    lo, hi = 1e1, 1e5
    for _ in range(28):
        mid = np.sqrt(lo * hi)
        lab, _ = develop(fol, mat, mid)
        if float(np.median(lab[0, :, 0]) * 100 / 255) < REAL["fol_L"]: lo = mid
        else: hi = mid
    return np.sqrt(lo * hi)


# Soil chromaticity is weighted equal to foliage: the previous fit let soil b* drift by 7 units
# because soil carried half the weight and the saturation term dominated everything.
TARGETS = [("fol_hue", 2.0), ("fol_a", 1.0), ("fol_b", 1.0),
           ("soil_a", 1.0), ("soil_b", 1.0), ("veg_sat", 400.0)]


def cost(p):
    mat = p.reshape(3, 3)
    s = stats(mat, fit_gain(mat))
    return sum(w * (s[k] - REAL[k]) ** 2 for k, w in TARGETS)


ccm0 = np.asarray(cp.read_ccm("calib/ccm_camA_20230728.xml"), float)
print(f"start cost {cost(ccm0.ravel()):.2f}", flush=True)
res = minimize(cost, ccm0.ravel(), method="Powell",
               options=dict(maxiter=60000, maxfev=6000, xtol=1e-3, ftol=1e-3))
mat = res.x.reshape(3, 3)
gain = fit_gain(mat)
print(f"final cost {res.fun:.2f} after {res.nfev} evaluations; fitted gain {gain:.1f}\n", flush=True)

before, after = stats(ccm0, fit_gain(ccm0)), stats(mat, gain)
fitted = {k for k, _ in TARGETS}
print(f"{'statistic':>10} {'real':>8} {'board CCM':>11} {'scene-fit':>11}   in objective")
for k in ("fol_hue", "fol_a", "fol_b", "veg_sat", "soil_a", "soil_b", "fol_L", "soil_L"):
    print(f"{k:>10} {REAL[k]:8.2f} {before[k]:11.2f} {after[k]:11.2f}   "
          f"{'yes' if k in fitted else 'NO (check)'}")

cb.write_ccm_xml(mat.T, "calib/ccm_camA_scenefit.xml", camera_label="camA",
                 note="Fitted against scene foliage/soil colour, not the colour board. "
                      "Excludes foliage and soil L* from the objective: the first is set by exposure "
                      "and the second is a soil reflectance error a colour matrix must not absorb.")
np.save("calib/ccm_camA_scenefit.npy", mat)
print(f"\nwrote calib/ccm_camA_scenefit.xml   (gain for develop.py: {gain:.1f})")
os.system(f"rm -rf {RAW}")
print("SCENE CCM FIT COMPLETE")
