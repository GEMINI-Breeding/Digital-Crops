"""Solve the real camera's colour transform from colour-board frames.

Output feeds RadiationModel::applyCameraColorCorrectionMatrix(). The matrix maps
white-balanced predicted camera RGB (what Helios produces) onto the RGB the real
camera actually writes -- i.e. it stands in for the ISP colour-correction stage
that Helios does not model.
"""
import numpy as np

from .colorboard import (reference_linear_rgb, load_illuminants,
                         srgb_to_linear, linear_to_srgb, write_ccm_xml)
from .board_extract import extract

SAT = 250.0   # any channel at/above this is clipped and carries no information


def linearize(x, gamma):
    return np.clip(np.asarray(x, float) / 255.0, 0, 1) ** gamma


def delinearize(x, gamma):
    return 255.0 * np.clip(x, 0, 1) ** (1.0 / gamma)


def solve_gamma(pred_lin, obs_srgb, mask, gammas=np.arange(1.6, 3.01, 0.05)):
    """Fit the tone curve jointly with the matrix.

    A camera JPEG applies its own tone curve, not textbook sRGB gamma. Assuming
    sRGB leaves that mismatch in the residual and biases the matrix, so the
    exponent is fitted rather than assumed. The neutral patch ramp is what
    constrains it.
    """
    best = None
    for g in gammas:
        P = pred_lin[mask] / pred_lin[mask].mean()
        O = linearize(obs_srgb[mask], g)
        sc = O.mean(); O = O / sc
        M, *_ = np.linalg.lstsq(P, O, rcond=None)
        fit = delinearize(np.clip(P @ M, 0, None) * sc, g)
        rms = float(np.sqrt(((fit - obs_srgb[mask]) ** 2).mean()))
        if best is None or rms < best[0]:
            best = (rms, float(g), M, fit)
    return best


def solve(pred_lin, obs_srgb, mask=None):
    """Least-squares 3x3 mapping predicted -> observed in linear light."""
    if mask is None:
        mask = np.ones(len(obs_srgb), bool)
    P = pred_lin[mask]
    O = srgb_to_linear(obs_srgb[mask])
    P = P / P.mean()
    scale = O.mean()
    O = O / scale
    M, *_ = np.linalg.lstsq(P, O, rcond=None)
    fit = linear_to_srgb(np.clip(P @ M, 0, None) * scale)
    rms = float(np.sqrt(((fit - obs_srgb[mask]) ** 2).mean()))
    return M, rms, fit, mask


def identity_baseline(pred_lin, obs_srgb, mask):
    """RMS if we applied NO colour matrix (only a per-channel gain).

    This is the number the CCM has to beat for the matrix to be worth having.
    """
    P = pred_lin[mask] / pred_lin[mask].mean()
    O = srgb_to_linear(obs_srgb[mask]); scale = O.mean(); O = O / scale
    g = (O / np.maximum(P, 1e-9)).mean(0)
    fit = linear_to_srgb(np.clip(P * g, 0, None) * scale)
    return float(np.sqrt(((fit - obs_srgb[mask]) ** 2).mean())), g


def calibrate(image_path, roi, board='spyder24', label='camA'):
    import cv2
    img = cv2.cvtColor(cv2.imread(image_path), cv2.COLOR_BGR2RGB)
    ext = extract(img, roi, board)
    obs = ext['patches']
    mask = (obs < SAT).all(1)

    rows = []
    for name, sp in sorted(load_illuminants().items()):
        pred = reference_linear_rgb(sp, board=board)
        if pred.sum() <= 0:
            continue
        rms, gamma, M, fit = solve_gamma(pred, obs, mask)
        base, gain = identity_baseline(pred, obs, mask)
        rows.append(dict(illuminant=name, rms=rms, gamma=gamma,
                         baseline_rms=base, M=M, gain=gain))
    rows.sort(key=lambda r: r['rms'])
    return dict(extract=ext, obs=obs, mask=mask, results=rows)
