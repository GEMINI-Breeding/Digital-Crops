"""Real T4 rover frames: where they are, how the camera saw them, what is in them.

Camera model. The rover's own configuration (`config/camA.pbtxt` in the 2023-07-25 calibration
session) carries a PLUMB_BOB calibration of camera A. It is used here in preference to the
datasheet-derived field of view the distribution harness assumed: fx = 1787.6 px means an
8.6 mm lens on the 4.8 um PYTHON 5000 pixel, not the 12 mm the harness inferred, and k1 = -0.127
bends the frame corners inward by 7 %, which no pinhole model can absorb. Every real frame is
undistorted to the pinhole model with the calibrated focal length before anything is measured
from it, and the synthetic camera is given that same focal length.
"""
import glob
import json
import os

import cv2
import numpy as np

DATASET = "/group/jmearlesgrp/GEMINI/heesup/dataset/2023_davis_cowpea_dataset"
DATES = ["2023-06-20", "2023-06-27", "2023-07-03", "2023-07-07", "2023-07-14", "2023-07-18", "2023-07-25", "2023-07-28"]

#: Basler acA2500-20gc "color_A", PLUMB_BOB, from the rover configuration.
FX, FY, CX, CY = 1787.5853551377443, 1788.3847441443984, 1301.3266577839895, 1022.607807458233
DIST = np.array([-0.12711273050637922, 0.055003054860061476, -0.00026893505248465327, -0.00038737026084712531, 0.0])
WIDTH, HEIGHT = 2592, 2048
#: Camera height above the soil, from rover_details.json (the harness previously assumed 1.64).
CAMERA_HEIGHT_M = 1.5

#: Horizontal field of view implied by the calibrated focal length across the full sensor width.
HFOV_DEG = float(np.degrees(2.0 * np.arctan(0.5 * WIDTH / FX)))


def K():
    return np.array([[FX, 0, CX], [0, FY, CY], [0, 0, 1.0]])


def frames(date, plot="Plot286-MAGIC083"):
    """All camA frames of one plot on one date, in capture order."""
    return sorted(glob.glob(f"{DATASET}/{date}/T4/{plot}/camA/*.jpg"))


def load(path):
    """Real frame as RGB uint8, distortion removed, principal point moved to the frame centre.

    The synthetic camera is an ideal pinhole with square pixels and the optical axis through the
    frame centre. `cv2.undistort` with a new camera matrix whose principal point is the centre
    and whose focal length is the calibrated fx brings the real frame to exactly that model, so
    a rasterized map at the same fx overlays it with no further alignment.
    """
    bgr = cv2.imread(path, cv2.IMREAD_COLOR)
    if bgr is None:
        raise FileNotFoundError(path)
    newK = np.array([[FX, 0, WIDTH / 2.0], [0, FX, HEIGHT / 2.0], [0, 0, 1.0]])
    und = cv2.undistort(bgr, K(), DIST, None, newK)
    return cv2.cvtColor(und, cv2.COLOR_BGR2RGB)


# ---------------------------------------------------------------- masks ---

def lab(rgb):
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32) * np.array([100.0 / 255.0, 1.0, 1.0]) - np.array([0.0, 128.0, 128.0])


def vegetation_mask(rgb, a_threshold=-8.0, min_area_px=400):
    """Green vegetation on the CIELAB a* axis, with speckle removed.

    a* rather than excess green: the distribution harness found ExG classifies brown soil as
    vegetation once a colour matrix has crushed the blue channel, and the real JPEGs carry the
    camera's own saturation boost. The threshold is checked against the sparse 2023-06-20 frames,
    where soil and plants are cleanly separable and the answer is visible by eye.
    """
    L = lab(rgb)
    veg = (L[..., 1] < a_threshold).astype(np.uint8)
    veg = cv2.morphologyEx(veg, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    n, lbl, stats, _ = cv2.connectedComponentsWithStats(veg, connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= min_area_px
    return keep[lbl]


def exg_mask(rgb, threshold=0.10, min_area_px=400):
    """Excess-green vegetation mask (2G - R - B on chromaticity-normalized RGB above `threshold`), speckle removed.
    The multi-crop package segments its sorghum frames this way; cowpea keeps the a* mask above."""
    f = rgb.astype(np.float32)
    s = f.sum(-1) + 1e-6
    r, g, b = f[..., 0] / s, f[..., 1] / s, f[..., 2] / s
    veg = ((2.0 * g - r - b) > threshold).astype(np.uint8)
    veg = cv2.morphologyEx(veg, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    n, lbl, stats, _ = cv2.connectedComponentsWithStats(veg, connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= min_area_px
    return keep[lbl]


def species_vegetation_mask(rgb, method="a_star", **kw):
    """The vegetation mask a species' table entry names (twin.species: "a_star" or "exg")."""
    if method == "a_star":
        return vegetation_mask(rgb, **kw)
    if method == "exg":
        return exg_mask(rgb, **kw)
    raise ValueError(f"unknown vegetation mask {method!r}")


def rover_mask(rgb):
    """Pixels belonging to the rover frame: dark or neutral metal, left and right of the bed.

    The rover is rigid relative to the camera, so the mask is the same in every frame; it is
    estimated once from colour (low chroma, not soil-toned) inside the two outer bands where the
    rails sit, then filled. Anything inside it is excluded from every comparison.
    """
    L = lab(rgb)
    chroma = np.hypot(L[..., 1], L[..., 2])
    H, W = chroma.shape
    band = np.zeros((H, W), bool)
    band[:, : int(0.20 * W)] = True
    band[:, int(0.80 * W) :] = True
    metal = band & (chroma < 12.0)
    metal = cv2.morphologyEx(metal.astype(np.uint8), cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31)))
    # keep only the large components touching the frame edge
    n, lbl, stats, _ = cv2.connectedComponentsWithStats(metal, connectivity=8)
    keep = np.zeros(n, bool)
    for k in range(1, n):
        x, y, w, h, a = stats[k]
        if a > 20000 and (x == 0 or x + w >= W):
            keep[k] = True
    return keep[lbl]


# ------------------------------------------------------------ structure ---

def row_profile(veg, rover):
    """Vegetation fraction per image column, rover excluded; rows run top-to-bottom in the frame."""
    valid = ~rover
    return (veg & valid).sum(0) / np.maximum(valid.sum(0), 1)


def find_rows(veg, rover, min_sep_px=300):
    """Column positions of the crop rows from the smoothed column profile."""
    p = row_profile(veg, rover)
    k = np.ones(101) / 101.0
    ps = np.convolve(p, k, mode="same")
    peaks = []
    for i in range(1, len(ps) - 1):
        if ps[i] >= ps[i - 1] and ps[i] >= ps[i + 1] and ps[i] > 0.15 * ps.max():
            if not peaks or i - peaks[-1] > min_sep_px:
                peaks.append(i)
            elif ps[i] > ps[peaks[-1]]:
                peaks[-1] = i
    return peaks, ps


def plant_centres(veg, min_area_px=1500, split_dist_px=140):
    """Plant footprints and centres for a sparse stand: connected components of the vegetation
    mask, split where a distance-transform peak analysis finds more than one plant in a blob.

    Adequate for the June frames, where plants barely touch. It is not attempted on a closed
    canopy: there the layout comes from the row geometry and sowing spacing, and per-plant
    presence is a fitted variable.
    """
    n, lbl, stats, cents = cv2.connectedComponentsWithStats(veg.astype(np.uint8), connectivity=8)
    out = []
    dist = cv2.distanceTransform(veg.astype(np.uint8), cv2.DIST_L2, 5)
    for k in range(1, n):
        if stats[k, cv2.CC_STAT_AREA] < min_area_px:
            continue
        x, y, w, h, a = stats[k]
        sub = (lbl[y : y + h, x : x + w] == k)
        d = dist[y : y + h, x : x + w] * sub
        # local maxima of the distance transform, separated by at least split_dist_px
        dil = cv2.dilate(d, np.ones((split_dist_px // 2 * 2 + 1,) * 2, np.uint8))
        pk = np.argwhere((d == dil) & (d > 0.35 * d.max()))
        if len(pk) == 0:
            pk = np.array([[int(cents[k][1] - y), int(cents[k][0] - x)]])
        # greedy non-maximum suppression
        pk = pk[np.argsort(-d[pk[:, 0], pk[:, 1]])]
        chosen = []
        for r, c in pk:
            if all(np.hypot(r - r2, c - c2) >= split_dist_px for r2, c2 in chosen):
                chosen.append((r, c))
        for r, c in chosen:
            out.append(dict(x=float(x + c), y=float(y + r), area_px=float(a) / len(chosen), component=int(k)))
    return out


def ground_xy(px, py, camera_height_m=CAMERA_HEIGHT_M, fx=FX, width=WIDTH, height=HEIGHT, sx=1.0, sy=1.0):
    """Image pixel -> bed coordinates on the soil plane, for the undistorted pinhole frame.

    The synthetic camera sits at (0, 0, camera_height) looking straight down; column grows with
    sx * x and row with -sy * y, the same convention as the label rasterizer in main.cpp.
    """
    x = sx * (px - width / 2.0) * camera_height_m / fx
    y = -sy * (py - height / 2.0) * camera_height_m / fx
    return x, y


def summary(path, out_json=None):
    rgb = load(path)
    veg = vegetation_mask(rgb)
    rov = rover_mask(rgb)
    valid = ~rov
    rows, _ = find_rows(veg, rov)
    s = dict(path=path, cover=float((veg & valid).sum() / valid.sum()), rover_frac=float(rov.mean()), rows_px=[int(r) for r in rows])
    if out_json:
        json.dump(s, open(out_json, "w"), indent=1)
    return s, rgb, veg, rov


# ------------------------------------------------------------- TomatoWUR ---
# I/O for a frame that is not the rover's (T5, 2026-09-29): TomatoWUR (4TU, CC BY-SA 4.0), potted tomato plants on a
# turntable seen by 15 calibrated 1080 x 1920 cameras (three rings of five; cams 0-4 look about 37 deg down). No rover,
# no soil: the fit is given the plant mask of the dataset's label image and the camera as a full pose (camera.pose in
# main.cpp's label rasterizer). The camera model is the one of the benchmark's TomatoWUR scripts
# (scratch/20260928_tomato/wur/wur_common.camera): the principal point is moved to the image center and the image
# downsampled by `down` with a >= 50 % coverage rule; hfov from fx (fx and fy differ by < 0.1 %).

WUR_ROOT = "/group/jmearlesgrp/heesup/dataset/external/tomatowur/TomatoWUR"
WUR_ANN = WUR_ROOT + "/ann_versions/0-paper-2Dto3D_improved/annotations"
WUR_PLANT_CLASSES = (1, 2, 4)      # leaves, main stem, side stem
WUR_POLE = 3                       # the support pole, ignored in every comparison


def wur_camera(cam, down=4):
    """TomatoWUR camera `cam` as dict(eye, x_axis (image right), y_axis (image up), z_axis (backward), hfov_deg, width,
    height, shift_px): world metres, z up; shift_px is the full-resolution (dx, dy) that centers the principal point."""
    d = json.load(open(f"{WUR_ROOT}/camera_poses/{cam}.json"))
    E = np.array(d["extrinsics"], dtype=np.float64).reshape(4, 4)
    Rm, t = E[:3, :3], E[:3, 3]
    K = d["intrinsics"]
    W, H = int(K["width"]), int(K["height"])
    return dict(eye=-Rm.T @ t, x_axis=Rm[0].copy(), y_axis=-Rm[1].copy(), z_axis=-Rm[2].copy(),
                hfov_deg=float(np.degrees(2.0 * np.arctan(0.5 * W / float(K["fx"])))), width=W // down, height=H // down,
                shift_px=(int(round(W / 2 - float(K["cx"]))), int(round(H / 2 - float(K["cy"])))))


def pose_overrides(cam, origin=(0.0, 0.0, 0.0)):
    """Rasterizer overrides for a posed camera (wur_camera form), in the twin frame = the world shifted so `origin` (the
    plant's base) is the twin's origin."""
    eye = np.asarray(cam["eye"], float) - np.asarray(origin, float)
    q = list(eye) + list(cam["x_axis"]) + list(cam["y_axis"]) + list(cam["z_axis"])
    return {"camera.pose": ",".join(f"{float(v):.9g}" for v in q), "camera.hfov": round(float(cam["hfov_deg"]), 6),
            "camera.resolution_x": int(cam["width"]), "camera.resolution_y": int(cam["height"]),
            "camera.height": round(float(eye[2]), 6), "scene.load_rover": 0, "raster.ground": 0}


def _shift(img, dx, dy, fill=0):
    out = np.full_like(img, fill)
    H, W = img.shape[:2]
    ys, yd = (slice(0, H - dy), slice(dy, H)) if dy >= 0 else (slice(-dy, H), slice(0, H + dy))
    xs, xd = (slice(0, W - dx), slice(dx, W)) if dx >= 0 else (slice(-dx, W), slice(0, W + dx))
    out[yd, xd] = img[ys, xs]
    return out


def _pool(b, down, thr=0.5):
    H, W = (b.shape[0] // down) * down, (b.shape[1] // down) * down
    return b[:H, :W].reshape(H // down, down, W // down, down).mean((1, 3)) >= thr


def wur_view(plant, cam, down=4):
    """(rgb, plant mask, pole mask) of one TomatoWUR view at the camera's centered, downsampled raster."""
    c = wur_camera(cam, down)
    dx, dy = c["shift_px"]
    lab_img = cv2.imread(f"{WUR_ANN}/{plant}/{plant}_cam_{cam:02d}.png", cv2.IMREAD_UNCHANGED)
    if lab_img.ndim == 3:
        lab_img = lab_img[..., 0]
    lab_img = _shift(lab_img, dx, dy, 0)
    bgr = _shift(cv2.imread(f"{WUR_ROOT}/images/{plant}/{plant}_cam_{cam:02d}.png", cv2.IMREAD_COLOR), dx, dy, 0)
    rgb = cv2.resize(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), (c["width"], c["height"]), interpolation=cv2.INTER_AREA)
    return rgb, _pool(np.isin(lab_img, WUR_PLANT_CLASSES), down), _pool(lab_img == WUR_POLE, down, 0.25)


def no_rover_mask(shape):
    """A rover mask for a frame without a rover (synthetic scenes, TomatoWUR): nothing excluded."""
    return np.zeros(shape, bool)
