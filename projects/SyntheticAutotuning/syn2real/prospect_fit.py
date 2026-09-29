"""Choose cowpea leaf pigment parameters so the RENDERED foliage colour matches
the real images.

The grid is produced by `SyntheticAutotuning prospect-grid`, i.e. by the same
LeafOptics/PROSPECT code the renderer calls -- no Python re-implementation, so
what is fitted here is what will be rendered.

Matching target: the median RGB of ExG-classified foliage pixels in the real
tiles. Both the real camera and the Helios pipeline white-balance against a
neutral reference, so leaf chromaticity relative to white is comparable across
the two. Absolute saturation is NOT used as a hard target -- the real camera
applies its own JPEG saturation boost, which belongs in
applyCameraImageCorrections(), not in the leaf pigments.
"""
import numpy as np
from .spectra import load_spectra, resample, srgb_gamma, to_hsv

PARAM_NAMES = ['Cab', 'Car', 'Cant', 'N', 'Cw', 'Cdm']


def load_grid(path):
    with open(path) as f:
        f.readline()
        lo, hi, n = (int(x) for x in f.readline().split())
        nw = hi - lo + 1
        rows = np.loadtxt(f)
    params = rows[:, :6]
    R = rows[:, 6:6 + nw]
    T = rows[:, 6 + nw:6 + 2 * nw]
    wl = np.arange(lo, hi + 1, dtype=float)
    return params, R, T, wl


def camera_rgb(R, wl, light, q, white_balance=True):
    """Vectorized camera RGB for a matrix of reflectance spectra (n x nw)."""
    L = resample(light, wl)
    Q = np.stack([resample(x, wl) for x in q])          # 3 x nw
    sig = (R[:, None, :] * (L[None, None, :] * Q[None, :, :])).sum(-1)
    if white_balance:
        sig = sig / np.maximum((L[None, :] * Q).sum(-1)[None, :], 1e-12)
    return sig


def fit(grid_path, helios_root, target_rgb, n_report=8):
    params, R, T, wl = load_grid(grid_path)
    cam = load_spectra(helios_root + 'plugins/radiation/spectral_data/camera_spectral_library.xml',
                       want={'Basler_acA2500-20gc_red', 'Basler_acA2500-20gc_green',
                             'Basler_acA2500-20gc_blue'})
    light = load_spectra(helios_root + 'plugins/radiation/spectral_data/light_spectral_library.xml',
                         want={'CREE_XLamp_XHP70p2_6500K'})['CREE_XLamp_XHP70p2_6500K']
    q = (cam['Basler_acA2500-20gc_red'], cam['Basler_acA2500-20gc_green'],
         cam['Basler_acA2500-20gc_blue'])

    lin = camera_rgb(R, wl, light, q)
    disp = srgb_gamma(lin)

    # Match chromaticity (channel ratios), not absolute level: overall level is
    # set by exposure, which is a camera parameter rather than a leaf property.
    def chroma(a):
        return a / np.maximum(a.sum(1, keepdims=True), 1e-12)
    tgt = np.asarray(target_rgb, float)
    d = np.linalg.norm(chroma(disp) - chroma(tgt[None, :]), axis=1)
    order = np.argsort(d)
    return params, disp, d, order, tgt


if __name__ == '__main__':
    H = '/group/bnbaileygrp/bnbailey/Helios/'
    TARGET = (96.9, 120.6, 56.7)     # measured real foliage median RGB
    params, disp, d, order, tgt = fit('spectra/prospect_grid.txt', H, TARGET)

    th = to_hsv(np.array(tgt) / 255)
    print(f'target (real foliage):  RGB {tgt[0]:.0f},{tgt[1]:.0f},{tgt[2]:.0f}   '
          f'hue {th[0]:.0f}  sat {th[1]:.3f}  G/R {tgt[1]/tgt[0]:.2f}  G/B {tgt[1]/tgt[2]:.2f}')
    print()
    print(f"{'rank':>4} {'Cab':>6} {'Car':>6} {'Cant':>6} {'N':>5} {'Cw':>7} {'Cdm':>7} "
          f"{'hue':>6} {'sat':>6} {'G/R':>5} {'G/B':>5} {'chroma err':>10}")
    for i, k in enumerate(order[:8]):
        h, s, v = to_hsv(disp[k])
        r, g, b = disp[k]
        print(f'{i+1:4d} {params[k,0]:6.1f} {params[k,1]:6.1f} {params[k,2]:6.1f} {params[k,3]:5.2f} '
              f'{params[k,4]:7.4f} {params[k,5]:7.4f} {h:6.0f} {s:6.3f} {g/r:5.2f} {g/b:5.2f} {d[k]:10.4f}')

    best = params[order[:50]].mean(0)
    print()
    print('centroid of the 50 best-matching parameter sets (recommended starting point):')
    for n, v in zip(PARAM_NAMES, best):
        print(f'   {n:5} = {v:.4g}')

    # Which pigment actually drives colour? Spearman against hue and saturation.
    from scipy.stats import spearmanr
    hs = np.array([to_hsv(x) for x in disp])
    print()
    print(f"{'param':>6} {'rho(hue)':>10} {'rho(sat)':>10}   <- sensitivity for the Phase 4/5 optimizer")
    for j, n in enumerate(PARAM_NAMES):
        print(f'{n:>6} {spearmanr(params[:,j], hs[:,0]).statistic:10.3f} '
              f'{spearmanr(params[:,j], hs[:,1]).statistic:10.3f}')
