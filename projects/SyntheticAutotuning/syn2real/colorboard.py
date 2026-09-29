"""Solve the real camera's colour transform from a SpyderCHECKR 24 frame.

Why this matters: PROSPECT's achievable G/B envelope under the Basler response
tops out at 1.54 while real foliage sits at 2.13, so the colour gap cannot be a
leaf-pigment problem. It lives in the camera's colour processing -- the matrix
every ISP applies to undo the overlap of the Bayer filter passbands. A frame
containing a colour board pins that transform exactly instead of guessing.

Byproduct worth as much as the matrix: fitting the board under several candidate
illuminants and comparing residuals identifies what light the real images were
actually captured under. The synthetic scene assumes rover LEDs plus a weak
collimated sun; if the board says otherwise, the lighting model needs revisiting.
"""
import numpy as np
import cv2

from .spectra import load_spectra, resample

HELIOS = '/group/bnbaileygrp/bnbailey/Helios/'
COLOR_BOARD_DIR = HELIOS + 'plugins/radiation/spectral_data/color_board/'

# Board registry. `grid` is (rows, cols) of the patch array as it appears in the
# photograph; `prefix` matches the label convention in the Helios spectral XML.
BOARDS = {
    'spyder24': dict(xml=COLOR_BOARD_DIR + 'Datacolor_SpyderCHECKR_24_colorboard.xml',
                     prefix='ColorReference_SpyderCHECKR_', n=24, grid=(4, 6)),
    'dgk18':    dict(xml=COLOR_BOARD_DIR + 'DGK_DKK_colorboard.xml',
                     prefix='ColorReference_DGK_', n=18, grid=(3, 6)),
    'calibrite24': dict(xml=COLOR_BOARD_DIR + 'Calibrite_ColorChecker_Classic_colorboard.xml',
                        prefix='ColorReference_Calibrite_', n=24, grid=(4, 6)),
}

BOARD_XML = BOARDS['spyder24']['xml']
CAM_XML = HELIOS + 'plugins/radiation/spectral_data/camera_spectral_library.xml'
LIGHT_XML = HELIOS + 'plugins/radiation/spectral_data/light_spectral_library.xml'
SOLAR_XML = HELIOS + 'plugins/radiation/spectral_data/solar_spectrum_ASTMG173.xml'

N_PATCH = 24
GRID = (4, 6)   # rows, cols


def srgb_to_linear(x):
    x = np.clip(np.asarray(x, float) / 255.0, 0, 1)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(x):
    x = np.clip(np.asarray(x, float), 0, 1)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * x ** (1 / 2.4) - 0.055) * 255


def reference_linear_rgb(illuminant, board='spyder24', camera='Basler_acA2500-20gc', grid=None,
                         white_balance=True):
    """Predicted LINEAR camera RGB for every patch of `board` under `illuminant`.

    With white_balance=True the response is normalized by that of a perfect
    white diffuser under the same illuminant -- the same convention Helios'
    'auto' white balance uses. Without it the raw Basler response is strongly
    green-biased and even neutral patches come out tinted, which makes the
    reference useless for matching board orientation.
    """
    if grid is None:
        grid = np.arange(400, 751, 1.0)
    b = BOARDS[board]
    spec = load_spectra(b['xml'])
    cam = load_spectra(CAM_XML, want={f'{camera}_{c}' for c in ('red', 'green', 'blue')})
    Q = np.stack([resample(cam[f'{camera}_{c}'], grid) for c in ('red', 'green', 'blue')])
    L = resample(illuminant, grid)
    out = []
    for i in range(1, b['n'] + 1):
        R = resample(spec[f"{b['prefix']}{i:02d}"], grid)
        out.append((L * R * Q).sum(1))
    out = np.array(out)
    if white_balance:
        out = out / np.maximum((L * Q).sum(1)[None, :], 1e-12)
    return out


def load_illuminants():
    ill = {}
    ill.update(load_spectra(LIGHT_XML, want={'CREE_XLamp_XHP70p2_6500K', 'ActiveGrow_LED_RedBloom'}))
    ill.update(load_spectra(SOLAR_XML))
    return ill


def sample_patches(img_rgb, corners, grid=GRID, shrink=0.45):
    """Sample median RGB of each patch.

    `corners` is 4 (x, y) points in the image, ordered
    top-left, top-right, bottom-right, bottom-left, of the OUTER patch grid.
    A perspective transform maps the board to a canonical rectangle so the
    board does not have to be square-on to the camera.
    """
    rows, cols = grid
    W, H = 600, 400
    dst = np.float32([[0, 0], [W, 0], [W, H], [0, H]])
    M = cv2.getPerspectiveTransform(np.float32(corners), dst)
    warp = cv2.warpPerspective(img_rgb, M, (W, H))
    out = []
    for r in range(rows):
        for c in range(cols):
            cx, cy = (c + 0.5) * W / cols, (r + 0.5) * H / rows
            hw, hh = shrink * W / cols / 2, shrink * H / rows / 2
            patch = warp[int(cy - hh):int(cy + hh), int(cx - hw):int(cx + hw)]
            out.append(np.median(patch.reshape(-1, 3), 0))
    return np.array(out), warp


def solve_ccm(pred_linear, obs_srgb, fit_gamma=False):
    """Least-squares 3x3 mapping predicted -> observed, in linear light.

    Returns (M, residual_rms_DN, predicted_srgb). 24 patches against 9 unknowns
    is heavily over-determined, so unlike the 3-material fit attempted earlier
    the residual here is meaningful evidence.
    """
    obs_lin = srgb_to_linear(obs_srgb)
    # normalize both to unit mean so an unknown overall exposure/illuminant
    # magnitude does not enter the fit
    P = pred_linear / pred_linear.mean()
    O = obs_lin / obs_lin.mean()
    M, *_ = np.linalg.lstsq(P, O, rcond=None)
    fit = P @ M
    rms = float(np.sqrt(((linear_to_srgb(fit * obs_lin.mean()) - obs_srgb) ** 2).mean()))
    return M, rms, linear_to_srgb(fit * obs_lin.mean())


def identify_illuminant(obs_srgb, board='spyder24'):
    """Rank candidate illuminants by CCM residual. Lowest = best explanation."""
    rows = []
    for name, sp in sorted(load_illuminants().items()):
        pred = reference_linear_rgb(sp, board=board)
        if pred.sum() <= 0:
            continue
        M, rms, _ = solve_ccm(pred, obs_srgb)
        rows.append((name, rms, M))
    rows.sort(key=lambda r: r[1])
    return rows


def write_ccm_xml(M, path, camera_label='camA', note=''):
    """Write the matrix in the exact form applyCameraColorCorrectionMatrix() parses.

    M is the numpy convention `out = rgb @ M`, so output channel j takes
    coefficients M[:, j]; the XML wants one <row> per OUTPUT channel, hence M.T.
    """
    with open(path, 'w') as f:
        if note:
            f.write(f'<!-- {note} -->\n')
        f.write(f'<ColorCorrectionMatrix camera_label="{camera_label}" matrix_type="3x3">\n')
        for row in M.T:
            f.write('  <row>' + ' '.join(f'{x:.6f}' for x in row) + '</row>\n')
        f.write('</ColorCorrectionMatrix>\n')
