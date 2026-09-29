"""Locate a colour board and read its patches, validating orientation.

Board detection uses the matte black frame (far darker than soil) rather than
the patches themselves -- the patches merge into surrounding bright soil under
any saturation/brightness threshold.

Orientation is not assumed. The board may be rotated or flipped in the frame and
the XML patch order is row-major in only one of those arrangements, so all eight
dihedral arrangements are tried and the one whose sampled colours best correlate
with the reference colours wins. That doubles as a correctness check: a wrong
grid gives a visibly poor correlation.
"""
import numpy as np
import cv2

from .colorboard import BOARDS, reference_linear_rgb, load_illuminants, linear_to_srgb


def locate_board(img_rgb, expect_px=250):
    """Find a colour board anywhere in the frame by local chroma variance.

    A colour board is the only object in these scenes that packs many strongly
    different hues into a small area, so the variance of the Lab a*/b* channels
    over a board-sized window peaks on it. This replaces a "largest dark blob"
    heuristic that latched onto shadows and debris in cluttered frames.
    """
    lab = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    ab = lab[..., 1:]
    k = max(int(expect_px * 0.6) | 1, 9)
    var = np.zeros(img_rgb.shape[:2], np.float32)
    for c in range(2):
        m = cv2.blur(ab[..., c], (k, k))
        m2 = cv2.blur(ab[..., c] ** 2, (k, k))
        var += np.maximum(m2 - m * m, 0)
    var = cv2.GaussianBlur(var, (0, 0), expect_px / 6.0)
    _, _, _, loc = cv2.minMaxLoc(var)
    h = expect_px
    x0, y0 = max(loc[0] - h, 0), max(loc[1] - h, 0)
    x1, y1 = min(loc[0] + h, img_rgb.shape[1]), min(loc[1] + h, img_rgb.shape[0])
    return (x0, y0, x1, y1), loc


def find_board(img_rgb, expect_px=250, frac=0.40):
    """Two-stage board finder.

    Stage 1 locates the board by CHROMA variance only. That deliberately ignores
    a black/white checkerboard calibration target, which has enormous luminance
    variance but no chroma and would otherwise win.
    Stage 2 measures the extent inside a tight window around that centre using
    luminance-and-chroma variance, which is needed to include the neutral patch
    column in the board outline.
    """
    _, loc = locate_board(img_rgb, expect_px)
    h = int(expect_px * 0.9)
    x0, y0 = max(loc[0] - h, 0), max(loc[1] - h, 0)
    x1, y1 = min(loc[0] + h, img_rgb.shape[1]), min(loc[1] + h, img_rgb.shape[0])
    sub = img_rgb[y0:y1, x0:x1]
    box, rect = board_rect_from_chroma(sub, expect_px, frac)
    box = box + np.array([x0, y0], np.float32)
    (cx, cy), wh, ang = rect
    return box, ((cx + x0, cy + y0), wh, ang)


def board_rect_from_chroma(img_rgb, expect_px=250, frac=0.30):
    """Board outline from the chroma-variance map, independent of frame colour.

    The dark-frame refinement only works for boards with a black surround; the
    DGK board has a white one. Thresholding the variance map instead works for
    any board, because what identifies it is the density of distinct hues, not
    the colour of its border.
    """
    lab = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    k = max(int(expect_px * 0.25) | 1, 9)
    var = np.zeros(img_rgb.shape[:2], np.float32)
    # Include L as well as a*/b*: the neutral patch column has near-zero chroma
    # variance by construction, so a chroma-only map clips it off the board and
    # returns a 6x3 rectangle instead of 6x4.
    for c in range(3):
        m = cv2.blur(lab[..., c], (k, k))
        m2 = cv2.blur(lab[..., c] ** 2, (k, k))
        var += np.maximum(m2 - m * m, 0)
    var = cv2.GaussianBlur(var, (0, 0), expect_px / 12.0)
    m = (var > frac * var.max()).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    n, lab_i, st, _ = cv2.connectedComponentsWithStats(m, 8)
    i = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    pts = np.column_stack(np.where(lab_i == i))[:, ::-1].astype(np.float32)
    rect = cv2.minAreaRect(pts)
    return cv2.boxPoints(rect), rect


def detect_board(img_rgb, roi, v_thresh=0.34):
    x0, y0, x1, y1 = roi
    sub = img_rgb[y0:y1, x0:x1]
    V = cv2.cvtColor(sub, cv2.COLOR_RGB2HSV)[..., 2] / 255.0
    m = (V < v_thresh).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    # fill interior: the frame is a ring, the patches sit inside it
    ff = m.copy()
    h, w = ff.shape
    cv2.floodFill(ff, np.zeros((h + 2, w + 2), np.uint8), (0, 0), 1)
    m = m | (1 - ff)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), 8)
    if n < 2:
        raise RuntimeError('no dark component found in ROI')
    # Prefer the component whose filled area is board-like, not merely largest:
    # shadows and debris are often bigger than the board frame.
    cands = []
    for i in range(1, n):
        pts = np.column_stack(np.where(lab == i))[:, ::-1].astype(np.float32)
        if len(pts) < 200:
            continue
        rc = cv2.minAreaRect(pts)
        w, h = rc[1]
        if min(w, h) < 40:
            continue
        ar = max(w, h) / max(min(w, h), 1e-6)
        if ar > 2.6:
            continue
        cands.append((w * h, rc, i))
    if not cands:
        raise RuntimeError('no board-like dark component in ROI')
    cands.sort(key=lambda t: -t[0])
    rect = cands[0][1]
    box = cv2.boxPoints(rect) + np.array([x0, y0], np.float32)
    return box, rect


def order_corners(box):
    """Order 4 points tl, tr, br, bl."""
    c = box.mean(0)
    ang = np.arctan2(box[:, 1] - c[1], box[:, 0] - c[0])
    order = np.argsort(ang)
    b = box[order]
    start = np.argmin(b[:, 0] + b[:, 1])
    return np.roll(b, -start, axis=0)


def sample_grid(img_rgb, corners, rows, cols, inset=0.10, shrink=0.40, out=(480, 720)):
    W, H = out
    dst = np.float32([[0, 0], [W, 0], [W, H], [0, H]])
    M = cv2.getPerspectiveTransform(np.float32(corners), dst)
    warp = cv2.warpPerspective(img_rgb, M, (W, H))
    ix, iy = inset * W, inset * H
    gw, gh = W - 2 * ix, H - 2 * iy
    vals = []
    for r in range(rows):
        for c in range(cols):
            cx = ix + (c + 0.5) * gw / cols
            cy = iy + (r + 0.5) * gh / rows
            hw, hh = shrink * gw / cols / 2, shrink * gh / rows / 2
            p = warp[int(cy - hh):int(cy + hh), int(cx - hw):int(cx + hw)]
            vals.append(np.median(p.reshape(-1, 3), 0))
    return np.array(vals, float), warp


def dihedral(a, k):
    """One of the 8 dihedral arrangements of a (rows, cols, 3) patch array."""
    if k & 4:
        a = a.transpose(1, 0, 2)
    for _ in range(k & 3):
        a = np.rot90(a, 1, axes=(0, 1))
    return a.reshape(-1, 3)


def extract(img_rgb, roi, board='spyder24', illuminant='solar_spectrum_ASTMG173',
            inset=0.10, v_thresh=0.34):
    b = BOARDS[board]
    rows, cols = b['grid']
    if roi is None:
        box, rect = find_board(img_rgb)
    else:
        try:
            box, rect = detect_board(img_rgb, roi, v_thresh)
        except RuntimeError:
            box, rect = find_board(img_rgb)
    corners = order_corners(box)

    ref_lin = reference_linear_rgb(load_illuminants()[illuminant], board=board)
    ref = linear_to_srgb(ref_lin / ref_lin.max())

    # Sample ONCE in the board's own orientation, then permute. Re-sampling per
    # arrangement double-applied the transpose and produced garbage matches.
    (bw, bh) = rect[1]
    portrait = bh >= bw
    R, C = (max(rows, cols), min(rows, cols)) if portrait else (min(rows, cols), max(rows, cols))
    W = 480 if portrait else 720
    H = 720 if portrait else 480
    vals, warp = sample_grid(img_rgb, corners, R, C, inset, out=(W, H))
    grid_arr = vals.reshape(R, C, 3)

    def chroma(a):
        return a / np.maximum(a.sum(1, keepdims=True), 1e-9)

    best = None
    for k in range(8):
        arranged = dihedral(grid_arr, k)
        if len(arranged) != b['n']:
            continue
        cc = np.corrcoef(chroma(arranged).ravel(), chroma(ref).ravel())[0, 1]
        if best is None or cc > best[0]:
            best = (cc, k, arranged, warp)
    return dict(corr=best[0], arrangement=best[1], patches=best[2],
                warp=best[3], corners=corners, rect=rect, ref=ref)
