"""Assemble the twin animation: real rover pass, then the twin beside it, tilting off nadir and growing on.

Segments on a canvas two panes wide and one tall (the real frame's aspect):
  1. the rover's own frames as it passes the plots, played at their true 8 Hz, pane centred;
  2. a freeze, then the real pane slides to the left half and the twin fades in on the right at nadir;
  3. the twin's camera walks down from the rig's height to 0.95 m, so the tilt to come clears the rig;
  4. it tilts to 30 degrees off nadir, across the rows;
  5. the plants grow on for 15 more days at that viewpoint.

The tilted renders use a portrait sensor and are rotated 90 degrees here, which puts the rows upright at the real frame's
pixel scale; the nadir pane is the matching twin render itself.

Every twin render is developed with ONE gain, fitted on the nadir render against the real frame's foliage lightness, so the
sequence does not pump. Renders come from scripts/twin_anim_render.sh.
usage: twin_anim_build.py [--out twin_work/anim/cowpea_twin.mp4] [--fps 24] [--pane-width 960]
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cv2  # noqa: E402
import numpy as np  # noqa: E402

import twin.appearance as A  # noqa: E402
import twin.fit as F  # noqa: E402
import twin.raster as TR  # noqa: E402
import twin.real as R  # noqa: E402

FRAME = "2023-06-27_Plot298-MAGIC226"
ANIM_SUFFIX = "_v2"  # the renders made with the corrected geometry
DATASET = "/group/jmearlesgrp/GEMINI/heesup/dataset/2023_davis_cowpea_dataset/2023-06-27/T4"
CLIP_PLOTS = ["Plot299-MAGIC188", "Plot298-MAGIC226"]  # the rover's pass, in order, ending on the fitted frame
WB = (1.563, 1.0, 1.596)
REAL_HZ = 8.0  # the rover's frame rate: 0.125 s between frames

ap = argparse.ArgumentParser()
ap.add_argument("--out", default=os.path.join(TR.PROJECT, "twin_work", "anim", "cowpea_twin.mp4"))
ap.add_argument("--fps", type=int, default=24)
ap.add_argument("--pane-width", type=int, default=960)
ap.add_argument("--trim-start", type=float, default=1.5, help="seconds cut from the head of the rover's pass")
ap.add_argument("--still-hold", type=float, default=1.4, help="seconds the first real-beside-twin still is held")
ap.add_argument("--real-only", action="store_true", help="build only the segments that need no twin renders: the rover pass, the freeze and the slide")
a = ap.parse_args()

anim = os.path.join(TR.PROJECT, "twin_work", "anim", FRAME + ANIM_SUFFIX)
ccm = A.CP.read_ccm(os.path.join(TR.PROJECT, "calib", "ccm_camA_20230728.xml"))
fit = json.load(open(os.path.join(TR.PROJECT, "twin_work", FRAME + "_final", "fit.json")))
target = F.Target(fit["target"], os.path.join(TR.PROJECT, "twin_work", FRAME + "_final"))
PW = a.pane_width
PH = int(round(PW * R.HEIGHT / R.WIDTH))
CANVAS = (2 * PW, PH)


def pane(rgb):
    return cv2.resize(rgb, (PW, PH), interpolation=cv2.INTER_AREA)


def caption(img, text, right=False):
    if not text:
        return img
    img = img.copy()
    org = (16, PH - 18)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 1, cv2.LINE_AA)
    return img


# ---------------------------------------------------------------- the real pass ---
clip_paths = []
for plot in CLIP_PLOTS:
    clip_paths += sorted(glob.glob(os.path.join(DATASET, plot, "camA", "*.jpg")))
end = clip_paths.index(fit["target"])
clip_paths = clip_paths[: end + 1][int(round(a.trim_start * REAL_HZ)) :]
print(f"real clip: {len(clip_paths)} frames ending on the fitted frame ({len(clip_paths) / REAL_HZ:.1f} s at {REAL_HZ:.0f} Hz, "
      f"{a.trim_start:.1f} s trimmed from the head)")
real_panes = [pane(R.load(p)) for p in clip_paths]

# ---------------------------------------------------------------- the twin renders ---
def developed(folder, gain=None):
    raw = A.read_exr(glob.glob(os.path.join(folder, "*_raw.exr"))[0])
    if gain is None:
        veg = A.label_map(glob.glob(os.path.join(folder, "*_site.txt"))[0]) > 0 if glob.glob(os.path.join(folder, "*_site.txt")) else None
        gain = A.fit_gain(raw, A.lab_stats(target.rgb, target.veg)["L50"], veg if veg is not None else np.ones(raw.shape[:2], bool), wb=WB, ccm=ccm)
    return A.develop(raw, gain, wb=WB, ccm=ccm), gain


descend_panes, orbit_panes, grow_panes, nadir_pane = [], [], [], None
if not a.real_only:
    nadir_dir = os.path.join(anim, "nadir")
    dirs = {k: sorted(glob.glob(os.path.join(anim, k + "_*"))) for k in ("descend", "orbit", "grow")}
    missing = [k for k, v in dirs.items() if not v]
    if missing or not glob.glob(os.path.join(nadir_dir, "*_raw.exr")):
        raise SystemExit(f"missing renders ({missing or 'nadir'}); run scripts/twin_anim_render.sh first")
    # one gain for the whole sequence, from the nadir render against the real frame's foliage
    nadir_img, GAIN = developed(nadir_dir)
    print(f"gain {GAIN:.0f} from the nadir render, held for every twin frame")
    nadir_pane = pane(nadir_img)
    upright = lambda img: cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)  # portrait sensor -> upright rows
    descend_panes = [pane(upright(developed(d, GAIN)[0])) for d in dirs["descend"]]
    orbit_panes = [pane(upright(developed(d, GAIN)[0])) for d in dirs["orbit"]]
    grow_panes = [pane(upright(developed(d, GAIN)[0])) for d in dirs["grow"]]

# ---------------------------------------------------------------- the video ---
writer = cv2.VideoWriter(a.out, cv2.VideoWriter_fourcc(*"mp4v"), a.fps, CANVAS)
if not writer.isOpened():
    raise SystemExit(f"cannot open {a.out} for writing")
frames_written = 0


def put(canvas_bgr):
    global frames_written
    writer.write(canvas_bgr)
    frames_written += 1


def compose(left=None, right=None, left_x=0):
    """Canvas with the real pane at left_x (pixels from the left edge) and the twin pane on the right half."""
    canvas = np.zeros((PH, 2 * PW, 3), np.uint8)
    if right is not None:
        canvas[:, PW:] = cv2.cvtColor(right, cv2.COLOR_RGB2BGR)
    if left is not None:
        x = int(round(left_x))
        canvas[:, x : x + PW] = cv2.cvtColor(left, cv2.COLOR_RGB2BGR)
    return canvas


# 1. the rover's pass, at its own rate, centred
hold = max(1, int(round(a.fps / REAL_HZ)))
for k, p in enumerate(real_panes):
    for _ in range(hold):
        put(compose(left=caption(p, f"real  T4 rover  2023-06-27  frame {k + 1}/{len(real_panes)}"), left_x=PW // 2))

# 2. freeze, slide left, twin fades in
last_real = caption(real_panes[-1], "real  T4 rover  2023-06-27")
for _ in range(int(0.5 * a.fps)):
    put(compose(left=last_real, left_x=PW // 2))
slide = int(0.75 * a.fps)
for i in range(slide):
    t = (i + 1) / slide
    ease = 0.5 - 0.5 * np.cos(np.pi * t)  # ease in and out
    put(compose(left=last_real, left_x=(PW // 2) * (1 - ease)))
if a.real_only:
    for _ in range(int(1.0 * a.fps)):
        put(compose(left=last_real, left_x=0))
    writer.release()
    print(f"wrote {a.out}: {frames_written} frames, {frames_written / a.fps:.1f} s at {a.fps} fps, {CANVAS[0]}x{CANVAS[1]} (real segments only)")
    raise SystemExit(0)
twin_nadir = caption(nadir_pane, "Helios twin  nadir, 1.55 m")
for i in range(int(0.5 * a.fps)):
    t = (i + 1) / int(0.5 * a.fps)
    put(compose(left=last_real, right=(t * twin_nadir.astype(np.float32)).astype(np.uint8), left_x=0))
# The first frame with both panes up is the comparison the whole film exists to make; it gets long enough to read.
for _ in range(int(a.still_hold * a.fps)):
    put(compose(left=last_real, right=twin_nadir, left_x=0))


def play(panes, seconds, label):
    """Cross-fade through a list of renders over `seconds`, so 1-per-step sequences read continuously."""
    n = int(seconds * a.fps)
    for i in range(n):
        u = i / max(n - 1, 1) * (len(panes) - 1)
        k = int(np.floor(u))
        f = u - k
        img = panes[k] if k + 1 >= len(panes) or f == 0 else cv2.addWeighted(panes[k], 1 - f, panes[k + 1], f, 0)
        put(compose(left=last_real, right=caption(img, label(u)), left_x=0))


# 3. walk the camera down so the tilt clears the rig
# 12 rendered steps over the same 1.5 s rather than 6: the cross-fade between distant camera positions was what read
# as choppy, and no amount of interpolation between two far-apart renders fixes that.
play(descend_panes, 1.5, lambda u: f"Helios twin  camera {1.55355 - (1.55355 - 0.95) * u / (len(descend_panes) - 1):.2f} m")
# 4. tilt to 30 degrees, across the rows
play(orbit_panes, 2.0, lambda u: f"Helios twin  view {1 + 29 * u / (len(orbit_panes) - 1):.0f} deg off nadir")
# 5. grow on for 15 more days
play(grow_panes, 4.0, lambda u: f"Helios twin  +{15 * u / (len(grow_panes) - 1):.0f} days")
for _ in range(int(0.8 * a.fps)):
    put(compose(left=last_real, right=caption(grow_panes[-1], "Helios twin  +15 days"), left_x=0))

writer.release()
print(f"wrote {a.out}: {frames_written} frames, {frames_written / a.fps:.1f} s at {a.fps} fps, {CANVAS[0]}x{CANVAS[1]}")
