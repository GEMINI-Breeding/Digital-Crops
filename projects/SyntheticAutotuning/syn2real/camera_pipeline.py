"""Re-run the Helios camera post-processing chain on dumped raw radiance.

Everything the renderer does to a pixel after the ray trace -- exposure, white balance, colour
matrix, tone curve, sRGB encoding -- is a per-pixel function of the three linear radiance
channels. Dumping those channels once (``output.write_exr 1``, with ``camera.exposure manual`` so
the dump is not already exposed) therefore makes every camera parameter tunable without touching
the ray tracer: a sweep that took a GPU-hour per point takes about a second per point here.

What this does NOT cover, because it changes what the rays carry rather than how the sensor reads
them: light source flux and spectrum, scattering depth, leaf pigments and soil reflectance,
specular scale, and anything geometric. Those still need a render.

The functions below mirror ``RadiationCamera``/``RadiationModel`` in
``plugins/radiation/src/RadiationCamera.cpp`` operation for operation, and the pipeline is
validated against the renderer's own JPEG by ``validate()``. Where the C++ and this file disagree,
the C++ is right and this file is the bug.
"""

from __future__ import annotations

import cv2
import numpy as np
import OpenEXR

# Rec.709 luminance weights, as used by RadiationCamera::luminance() and by the shadow-rolloff and
# pedestal terms of this project's own post-processing.
LUMA = (0.2126, 0.7152, 0.0722)

#: The development settings for this dataset. THESE TWO MUST CHANGE TOGETHER: the gain is bisected
#: to put foliage at the real median L* through a PARTICULAR colour matrix, so pairing one with the
#: other's value silently mis-exposes every image. They were separate hard-coded literals in nine
#: files before this, which is exactly the drift this prevents.
#:
#: ccm_camA_scenefit.xml is fitted against scene foliage and soil colour rather than the calibration
#: board; the board matrix it replaces put foliage hue at 117.2 against a real 123.5. See
#: scripts/fit_scene_ccm.py.
DEVELOP_CCM = "calib/ccm_camA_scenefit.xml"

#: Real foliage median lightness. This, not a gain, is the thing that transfers between
#: configurations: the gain that reaches it depends on how much light the canopy intercepts, which
#: leaf angle, density and architecture all change. 648.7 suits the trial-18 canopy and 374.0 the
#: planophile one -- a factor of 0.58 for a change that was only meant to affect appearance.
#: Prefer develop.py --target-L over --gain for anything but reproducing an existing dataset.
REAL_FOLIAGE_L = 47.84
DEVELOP_GAIN = 648.7          #: trial-18 canopy only; recalibrate for any other


# --------------------------------------------------------------------------- I/O ---


def read_raw_exr(path):
    """Read a 3-channel raw radiance EXR written by RadiationModel::writeCameraImageDataEXR.

    Returns float32 (H, W, 3) in R, G, B order, in the orientation of the renderer's JPEG.

    No flip is applied. writeCameraImageDataEXR() flips horizontally and writeCameraImage() flips
    both axes, which suggests the EXR should be mirrored vertically relative to the JPEG -- but the
    EXR row order and the reader's cancel that second flip, and the arrays come back aligned. This
    was checked against the renderer's own JPEG rather than reasoned from the writers: of the four
    orientations, this one gives 1.2/255 mean error and the other three give 40-42/255.
    """
    # Read through the OpenEXR bindings rather than cv2: the OpenCV wheels available here are
    # built without EXR support and return None for every EXR, which is indistinguishable from a
    # missing file.
    with OpenEXR.File(path) as handle:
        channels = handle.parts[0].channels
        if "RGB" in channels:
            rgb = np.asarray(channels["RGB"].pixels, dtype=np.float32)
        elif all(c in channels for c in "RGB"):
            rgb = np.stack([np.asarray(channels[c].pixels, dtype=np.float32) for c in "RGB"], axis=-1)
        else:
            raise ValueError(f"expected RGB channels, found {sorted(channels)}: {path}")
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError(f"expected a 3-channel EXR, got shape {rgb.shape}: {path}")
    return np.ascontiguousarray(rgb)


def read_ccm(path):
    """Read a 3x3 colour correction matrix from the XML written by autoCalibrateCameraImage."""
    rows = []
    with open(path) as handle:
        for line in handle:
            start, end = line.find("<row>"), line.find("</row>")
            if start != -1 and end != -1:
                rows.append([float(v) for v in line[start + 5 : end].split()])
    if len(rows) != 3 or any(len(r) != 3 for r in rows):
        raise ValueError(f"CCM file did not contain a 3x3 matrix: {path}")
    return np.array(rows, dtype=np.float32)


# ------------------------------------------------------------------ pipeline stages ---


def luminance(rgb):
    return rgb[..., 0] * LUMA[0] + rgb[..., 1] * LUMA[1] + rgb[..., 2] * LUMA[2]


def auto_exposure(rgb, target=0.18):
    """RadiationCamera::applyCameraExposure(), "auto" mode for an RGB camera.

    Gain is the multiplier that puts the median pixel luminance at 18% grey, applied to all three
    channels. Returns (exposed image, gain) so the gain can be reported or reused.
    """
    if not np.all(np.isfinite(rgb)):
        # The C++ refuses to expose a non-finite frame rather than scaling everything by NaN and
        # producing a black image with no diagnostic. Same reasoning applies here.
        raise ValueError("raw radiance contains non-finite values; the ray trace that produced it failed")
    median = float(np.median(luminance(rgb)))
    gain = target / max(median, 1e-6)
    return rgb * gain, gain


def white_balance(rgb, factors):
    """Per-channel gain. This project computes the factors from the camera response curves
    integrated against the illuminant, which makes them scene-independent constants."""
    return rgb * np.asarray(factors, dtype=np.float32)


def apply_ccm(rgb, matrix, strength=1.0, shadow_lo=0.0, shadow_hi=0.0):
    """Colour correction matrix with the strength blend and shadow rolloff used by main.cpp.

    ``strength`` blends the matrix toward the identity; ``shadow_lo``/``shadow_hi`` smoothstep the
    correction off in dark pixels, where an unconstrained matrix drives channels negative.
    """
    matrix = strength * matrix + (1.0 - strength) * np.eye(3, dtype=np.float32)
    corrected = rgb @ matrix.T
    if shadow_hi > shadow_lo:
        a = np.clip((luminance(rgb) - shadow_lo) / (shadow_hi - shadow_lo), 0.0, 1.0)
        a = (a * a * (3.0 - 2.0 * a))[..., None]
        corrected = a * corrected + (1.0 - a) * rgb
    return np.maximum(corrected, 0.0)


def tone_curve(rgb, black_level=0.0, highlight_knee=0.0):
    """Highlight rolloff then a chroma-preserving black-level lift, in that order.

    The lift scales all three channels by the same factor so that shadows are raised without being
    desaturated, which a per-channel pedestal would do.
    """
    out = np.maximum(rgb, 0.0)
    if highlight_knee > 0.0:
        k = highlight_knee
        # Evaluated only above the knee: below it the denominator passes through zero, which would
        # produce infinities that np.where discards but numpy still warns about.
        above = out > k
        excess = np.where(above, out - k, 0.0)
        out = np.where(above, k + excess / (1.0 + excess / k), out)
    if black_level > 0.0:
        Y = luminance(out)
        Yp = black_level + Y * (1.0 - black_level)
        scale = np.where(Y > 1e-6, Yp / np.maximum(Y, 1e-6), 0.0)
        out = np.where((Y > 1e-6)[..., None], out * scale[..., None], Yp[..., None])
    return out


def adjust_saturation(rgb, saturation):
    """RadiationCamera::adjustSaturation(): lerp each channel toward the pixel's luminance.

    Applied in linear space after the tone curve and before sRGB encoding, which is where
    applyCameraImageCorrections() sits in the renderer's order.
    """
    if saturation == 1.0:
        return rgb
    lum = luminance(rgb)[..., None]
    return lum + saturation * (rgb - lum)


def lin_to_srgb(x):
    """RadiationCamera::lin_to_srgb(), including its clamp of >=1 to white."""
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1.0 / 2.4) - 0.055)


# ------------------------------------------------------------------ sensor effects ---
#
# These have no counterpart in the renderer. They are the measured differences between a rendered
# frame and a real one: a real sensor has read noise, a real lens is not perfectly sharp, and the
# real dataset was JPEG-encoded at a much lower quality than Helios writes.


def add_read_noise(rgb01, sigma, rng, correlation=2):
    """Spatially-correlated Gaussian read noise, in display units.

    Demosaicing correlates neighbouring pixels, so per-pixel independent noise is measurably too
    high-frequency; a small blur of the noise field reproduces the real spatial statistics.
    """
    if sigma <= 0:
        return rgb01
    noise = rng.normal(0.0, sigma, size=rgb01.shape).astype(np.float32)
    if correlation > 1:
        noise = cv2.GaussianBlur(noise, (0, 0), correlation / 3.0)
        noise *= sigma / max(float(noise.std()), 1e-8)
    return np.clip(rgb01 + noise, 0.0, 1.0)


def add_blur(rgb01, sigma):
    """Isotropic defocus/demosaic softness, in display units."""
    if sigma <= 0:
        return rgb01
    return cv2.GaussianBlur(rgb01, (0, 0), sigma)


def jpeg_roundtrip(rgb01, quality):
    """Encode and decode at a given JPEG quality, reproducing the real set's quantization."""
    bgr = np.clip(rgb01 * 255.0 + 0.5, 0, 255).astype(np.uint8)[:, :, ::-1]
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)[:, :, ::-1].astype(np.float32) / 255.0


# ----------------------------------------------------------------------- pipeline ---

#: Defaults matching config/baseline.cfg, so process() with no overrides reproduces the renderer.
DEFAULTS = dict(
    exposure="auto",
    white_balance=(1.563, 1.000, 1.596),
    ccm=None,
    ccm_strength=0.75,
    ccm_shadow_lo=0.0,
    ccm_shadow_hi=0.0,
    black_level=0.0,
    highlight_knee=0.55,
    saturation=1.0,
    noise_sigma=0.0,
    blur_sigma=0.0,
    jpeg_quality=None,
    seed=0,
)


def process(raw_rgb, **overrides):
    """Run the full chain on raw linear radiance, returning display-referred float RGB in [0,1].

    Stages run in the renderer's order: exposure, white balance, colour matrix, tone curve, sRGB
    encoding -- then the sensor effects, which act on display values as a real ISP's would.
    """
    cfg = dict(DEFAULTS)
    unknown = set(overrides) - set(DEFAULTS)
    if unknown:
        raise KeyError(f"unknown camera pipeline parameter(s): {sorted(unknown)}")
    cfg.update(overrides)

    out = np.asarray(raw_rgb, dtype=np.float32)
    if cfg["exposure"] == "auto":
        out, _ = auto_exposure(out)
    elif cfg["exposure"] != "manual":
        # An explicit numeric gain. The renderer also accepts "ISOxxx"; that is not replicated
        # here, and asking for it is an error rather than a silent fall-through to manual.
        try:
            out = out * float(cfg["exposure"])
        except (TypeError, ValueError):
            raise ValueError(f"exposure must be 'auto', 'manual', or a numeric gain; got {cfg['exposure']!r}")

    out = white_balance(out, cfg["white_balance"])
    if cfg["ccm"] is not None:
        matrix = cfg["ccm"] if isinstance(cfg["ccm"], np.ndarray) else read_ccm(cfg["ccm"])
        out = apply_ccm(out, matrix, cfg["ccm_strength"], cfg["ccm_shadow_lo"], cfg["ccm_shadow_hi"])
    out = tone_curve(out, cfg["black_level"], cfg["highlight_knee"])
    out = adjust_saturation(out, cfg["saturation"])
    out = lin_to_srgb(out).astype(np.float32)

    rng = np.random.default_rng(cfg["seed"])
    out = add_blur(out, cfg["blur_sigma"])
    out = add_read_noise(out, cfg["noise_sigma"], rng)
    if cfg["jpeg_quality"] is not None:
        out = jpeg_roundtrip(out, cfg["jpeg_quality"])
    return out


def validate(exr_path, reference_jpeg, **overrides):
    """Check the replica against the renderer's own output for the same frame.

    Returns (mean_abs_error, p99_abs_error) over all pixels and channels, in display units. The
    reference JPEG is lossy, so exact equality is not expected; a mean error of a couple of 1/255
    steps means the chain is matched and a much larger one means a stage is missing or misordered.
    """
    produced = process(read_raw_exr(exr_path), **overrides)
    ref = cv2.imread(reference_jpeg, cv2.IMREAD_COLOR)
    if ref is None:
        raise FileNotFoundError(f"could not read reference JPEG: {reference_jpeg}")
    ref = ref[:, :, ::-1].astype(np.float32) / 255.0
    if ref.shape != produced.shape:
        raise ValueError(f"shape mismatch: replica {produced.shape} vs reference {ref.shape}")
    err = np.abs(produced - ref)
    return float(err.mean()), float(np.percentile(err, 99))
