"""Tier-0 statistics derived from pixels: colour, canopy cover, texture, sensor.

Every function returns per-image scalars so that real and synthetic can be
compared as distributions rather than as single numbers.
"""
import numpy as np
import cv2

# Excess-green threshold on normalized chromaticity. Fixed (not Otsu) so the
# same decision boundary is applied to both domains -- an adaptive threshold
# would hide exactly the cover difference we are trying to measure.
EXG_THRESH = 0.05


def _exg(rgb):
    f = rgb.astype(np.float32) / 255.0
    s = f.sum(2) + 1e-6
    r, g, b = f[..., 0] / s, f[..., 1] / s, f[..., 2] / s
    return 2 * g - r - b


def _radial_psd_slope(gray):
    """Slope of log power vs log spatial frequency over the mid/high band.

    Rendered images characteristically carry excess high-frequency energy
    (no optical low-pass, no sensor noise floor), which shows up as a
    shallower (less negative) slope than real photographs.
    """
    g = gray.astype(np.float32) / 255.0
    g = g - g.mean()
    win = np.outer(np.hanning(g.shape[0]), np.hanning(g.shape[1]))
    F = np.fft.fftshift(np.fft.fft2(g * win))
    P = (F.real ** 2 + F.imag ** 2)
    h, w = P.shape
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.sqrt((yy - h / 2) ** 2 + (xx - w / 2) ** 2).astype(int)
    nbins = min(h, w) // 2
    tot = np.bincount(r.ravel(), P.ravel(), minlength=nbins + 1)[:nbins]
    cnt = np.bincount(r.ravel(), minlength=nbins + 1)[:nbins]
    prof = tot / np.maximum(cnt, 1)
    lo, hi = max(3, nbins // 32), nbins - 1
    f = np.arange(lo, hi)
    y = np.log(prof[lo:hi] + 1e-20)
    slope = np.polyfit(np.log(f), y, 1)[0]
    hf = prof[nbins // 4:].sum() / (prof[1:].sum() + 1e-20)
    return float(slope), float(hf)


def _noise_sigma(gray):
    """Immerkaer's fast noise estimate: response to a Laplacian-like kernel."""
    k = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], np.float32)
    r = cv2.filter2D(gray.astype(np.float32), -1, k)
    h, w = gray.shape
    return float(np.abs(r).sum() * np.sqrt(np.pi / 2) / (6.0 * (w - 2) * (h - 2)))


def _edge_width(gray):
    """Mean width of intensity edges -- a blur / optical-sharpness proxy."""
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.sqrt(gx * gx + gy * gy)
    strong = mag > np.percentile(mag, 95)
    lap = np.abs(cv2.Laplacian(gray, cv2.CV_32F, ksize=3))
    return float(mag[strong].mean() / (lap[strong].mean() + 1e-6))


def image_stats(rgb):
    """All per-image pixel statistics for one RGB uint8 image."""
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    L, A, B = lab[..., 0] * 100 / 255, lab[..., 1] - 128, lab[..., 2] - 128
    Hh, S, V = hsv[..., 0] * 2, hsv[..., 1] / 255, hsv[..., 2] / 255

    exg = _exg(rgb)
    veg = exg > EXG_THRESH
    vf = float(veg.mean())
    # Non-vegetation splits into genuinely-lit background (soil) and deep shadow.
    # Lumping them together made 'soil colour' meaningless in the closed real
    # canopies, where most non-green pixels are inter-leaf shadow, not soil.
    shadow = (~veg) & (L < 25)
    soil = (~veg) & (L >= 25)

    # local RMS contrast: std of L within 16x16 blocks, averaged
    bs = 16
    Lb = L[:L.shape[0] // bs * bs, :L.shape[1] // bs * bs]
    Lb = Lb.reshape(Lb.shape[0] // bs, bs, Lb.shape[1] // bs, bs).transpose(0, 2, 1, 3)
    local_rms = float(Lb.reshape(-1, bs * bs).std(1).mean())

    # specular highlights: bright and desaturated
    spec = float(((V > 0.85) & (S < 0.25)).mean())

    slope, hf = _radial_psd_slope(gray)

    st = {
        'veg_cover_frac':    vf,
        'soil_cover_frac':   float(soil.mean()),
        'shadow_frac':       float(shadow.mean()),
        'L_mean':            float(L.mean()),
        'L_p05_shadow':      float(np.percentile(L, 5)),
        'L_p95_highlight':   float(np.percentile(L, 95)),
        'L_std':             float(L.std()),
        'lab_a_mean':        float(A.mean()),
        'lab_b_mean':        float(B.mean()),
        'sat_mean':          float(S.mean()),
        'local_rms_contrast': local_rms,
        'specular_frac':     spec,
        'psd_slope':         slope,
        'hf_energy_frac':    hf,
        'noise_sigma':       _noise_sigma(gray),
        'edge_sharpness':    _edge_width(gray),
    }
    if veg.sum() > 100:
        st['veg_hue_deg']  = float(np.median(Hh[veg]))
        st['veg_sat']      = float(np.median(S[veg]))
        st['veg_value']    = float(np.median(V[veg]))
        st['veg_L']        = float(np.median(L[veg]))
    else:
        st['veg_hue_deg'] = st['veg_sat'] = st['veg_value'] = st['veg_L'] = np.nan
    if soil.sum() > 100:
        st['soil_L']       = float(np.median(L[soil]))
        st['soil_hue_deg'] = float(np.median(Hh[soil]))
        st['soil_sat']     = float(np.median(S[soil]))
    else:
        st['soil_L'] = st['soil_hue_deg'] = st['soil_sat'] = np.nan
    return st


def jpeg_quant_sum(path):
    """Sum of the luma quantization table -- a direct compression-level probe."""
    import struct
    d = open(path, 'rb').read()
    i, out = 2, []
    while i < len(d) - 1:
        if d[i] != 0xFF:
            break
        m = d[i + 1]
        if m in (0xD8, 0xD9):
            i += 2; continue
        if m == 0xDA:
            break
        ln = struct.unpack('>H', d[i + 2:i + 4])[0]
        if m == 0xDB:
            out.append(int(sum(d[i + 5:i + 69])))
        i += 2 + ln
    return out[0] if out else np.nan


def collect(ds, limit=None, workers=8):
    """Run image_stats over a dataset; returns dict of stat -> array."""
    from concurrent.futures import ThreadPoolExecutor
    stems = ds.stems if limit is None else ds.stems[:limit]

    def one(s):
        st = image_stats(ds.read_rgb(s))
        st['jpeg_quant_sum'] = jpeg_quant_sum(ds.image_path(s))
        return st

    with ThreadPoolExecutor(workers) as ex:
        rows = list(ex.map(one, stems))
    keys = rows[0].keys()
    return {k: np.array([r[k] for r in rows], float) for k in keys}
