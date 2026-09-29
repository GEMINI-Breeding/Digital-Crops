"""Turn paired real/synthetic statistic distributions into ranked discrepancies.

Three numbers per statistic:
  w1_norm    Wasserstein-1 distance / real IQR       -- overall distributional gap
  shift_norm (median_syn - median_real) / real IQR   -- signed centring error
  cov_deficit fraction of the real p5-p95 span NOT covered by the synthetic
             p5-p95 span -- the ASYMMETRIC term. Being wider than real costs
             nothing; failing to reach real modes is what gets penalized.
"""
import numpy as np
from scipy.stats import wasserstein_distance

# which Helios parameter family controls each statistic -- drives the plan's phasing
CONTROLS = {
    'obj_width_px': 'architecture:inflorescence', 'obj_height_px': 'architecture:inflorescence',
    'obj_size_px': 'camera:GSD + architecture:flower_scale',
    'obj_log_aspect': 'architecture:flower/peduncle orientation',
    'obj_major_px': 'architecture:flower_scale', 'obj_minor_px': 'architecture:flower_scale',
    'obj_abs_log_aspect': 'architecture:flower shape',
    'shadow_frac': 'photometry:light geometry + canopy depth',
    'obj_center_x': 'camera:framing', 'obj_center_y': 'camera:framing',
    'img_obj_count': 'architecture:flower_bud_break_probability',
    'img_obj_area_frac': 'architecture:flower density x scale',
    'img_edge_trunc_frac': 'camera:tiling', 'img_nn_dist_px': 'architecture:phyllotaxy/spacing',
    'veg_cover_frac': 'scene:planting density + phenology', 'soil_cover_frac': 'scene:planting density + phenology',
    'L_mean': 'photometry:exposure', 'L_p05_shadow': 'photometry:light geometry + scattering depth',
    'L_p95_highlight': 'photometry:exposure + specular', 'L_std': 'photometry:contrast',
    'lab_a_mean': 'photometry:leaf spectra + white balance', 'lab_b_mean': 'photometry:leaf spectra + white balance',
    'sat_mean': 'photometry:saturation adjustment',
    'local_rms_contrast': 'photometry:light geometry', 'specular_frac': 'materials:specular_scale/exponent',
    'psd_slope': 'sensor:optical MTF + noise', 'hf_energy_frac': 'sensor:optical MTF + noise',
    'noise_sigma': 'sensor:shot/read noise', 'edge_sharpness': 'sensor:blur + lens_diameter',
    'veg_hue_deg': 'photometry:leaf reflectance spectra', 'veg_sat': 'photometry:leaf reflectance spectra',
    'veg_value': 'photometry:exposure', 'veg_L': 'photometry:exposure',
    'soil_L': 'photometry:soil reflectivity', 'soil_hue_deg': 'photometry:soil reflectivity',
    'soil_sat': 'photometry:soil reflectivity',
    'jpeg_quant_sum': 'sensor:JPEG encode quality',
}


def _clean(a):
    a = np.asarray(a, float)
    return a[np.isfinite(a)]


def compare_stat(real, syn):
    r, s = _clean(real), _clean(syn)
    if len(r) < 5 or len(s) < 5:
        return None
    # Scale by the WIDER of the two IQRs. Using the real IQR alone exploded the
    # metric whenever the real statistic was constant (e.g. every real image
    # shares one JPEG quantization table -> IQR 0 -> W1/IQR meaningless).
    iqr_r = np.percentile(r, 75) - np.percentile(r, 25)
    iqr_s = np.percentile(s, 75) - np.percentile(s, 25)
    scale = max(iqr_r, iqr_s)
    both_constant = scale <= 1e-12 and max(np.std(r), np.std(s)) <= 1e-12
    if scale <= 1e-12:
        scale = max(np.std(r), np.std(s), 1e-12)
    degenerate = iqr_r <= 1e-12
    rlo, rhi = np.percentile(r, [5, 95])
    slo, shi = np.percentile(s, [5, 95])
    span = rhi - rlo
    if span > 1e-12:
        overlap = max(0.0, min(rhi, shi) - max(rlo, slo))
        cov = overlap / span
    else:
        cov = 1.0 if slo <= rlo <= shi else 0.0
    return {
        'real_median': float(np.median(r)), 'syn_median': float(np.median(s)),
        'real_p5': float(rlo), 'real_p95': float(rhi),
        'syn_p5': float(slo), 'syn_p95': float(shi),
        'n_real': len(r), 'n_syn': len(s),
        'real_iqr_degenerate': bool(degenerate),
        # A statistic that is constant in BOTH domains (e.g. every image in each
        # set shares one JPEG quantization table) has no spread to normalize by.
        # Ranking it by W1/IQR is meaningless, so it is flagged and reported
        # separately as an exact-value mismatch.
        'both_constant': bool(both_constant),
        'w1_norm': float('nan') if both_constant else float(wasserstein_distance(r, s) / scale),
        'shift_norm': float('nan') if both_constant else float((np.median(s) - np.median(r)) / scale),
        'cov_deficit': float(1.0 - cov),
    }


def verdict(row):
    """Asymmetric reading of a gap.

    Being WIDER than real is not penalized -- the literature consensus (and the
    project's own prior) is that extra synthetic variability helps. What hurts
    is being centred in the wrong place, or being too narrow to reach the real
    modes at all.
    """
    if row.get('both_constant'):
        return 'CONSTANT-MISMATCH'
    sh, cd = abs(row['shift_norm']), row['cov_deficit']
    if sh > 0.5:
        return 'SHIFTED'
    if cd > 0.30:
        return 'TOO-NARROW'
    if row['syn_p5'] <= row['real_p5'] and row['syn_p95'] >= row['real_p95'] and sh <= 0.25:
        return 'WIDER-OK'
    if sh > 0.25 or cd > 0.15:
        return 'MINOR'
    return 'OK'


def compare_all(real_stats, syn_stats):
    rows = []
    for k in real_stats:
        if k not in syn_stats:
            continue
        c = compare_stat(real_stats[k], syn_stats[k])
        if c is None:
            continue
        c['stat'] = k
        c['controls'] = CONTROLS.get(k, '?')
        rows.append(c)
    import pandas as pd
    df = pd.DataFrame(rows).set_index('stat')
    df['verdict'] = [verdict(r) for _, r in df.iterrows()]
    order = {'CONSTANT-MISMATCH': 0, 'SHIFTED': 1, 'TOO-NARROW': 2, 'MINOR': 3, 'WIDER-OK': 4, 'OK': 5}
    df['_o'] = df['verdict'].map(order)
    df = df.sort_values(['_o', 'w1_norm'], ascending=[True, False]).drop(columns='_o')
    return df
