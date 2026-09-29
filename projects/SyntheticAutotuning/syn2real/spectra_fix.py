"""Remove the additive offset from the measured LI-COR leaf reflectance spectra.

Evidence for the offset (see PHASE1_FINDINGS.md):
  * At 680 nm -- the chlorophyll absorption maximum, where a healthy leaf both
    reflects and transmits almost nothing -- the measured spectra give
    R = 0.083 but T = 0.011. A real leaf cannot reflect 8x what it transmits
    in its deepest absorption band.
  * Subtracting one wavelength-flat constant brings BLUE (0.081 -> 0.03),
    RED (0.091 -> 0.04) and NIR (0.536 -> 0.48) simultaneously into agreement
    with canonical dicot values. A single constant fixing three widely
    separated bands at once is the signature of stray light / specular
    leakage in the reflectance channel, not leaf biology.
  * The green/red ratio rises from 1.81 (impossible for a green leaf) to
    ~4.3 (canonical).

The correction is applied to R only; T is left untouched.
"""
import re
import numpy as np

# True leaf reflectance at the chlorophyll absorption maximum. PROSPECT with
# Cab 30-50 gives 0.025-0.035 here; 0.030 is the midpoint.
R680_TRUE = 0.030
FLOOR = 0.002


def estimate_offset(spec, r680_true=R680_TRUE):
    """Offset for one spectrum = measured R(680) - true R(680), clipped at 0."""
    r680 = np.interp(680.0, spec[:, 0], spec[:, 1])
    return max(0.0, float(r680 - r680_true))


def correct(spec, offset=None):
    out = spec.copy()
    if offset is None:
        offset = estimate_offset(spec)
    out[:, 1] = np.clip(out[:, 1] - offset, FLOOR, None)
    return out


def rewrite_xml(in_path, out_path, r680_true=R680_TRUE, report=True):
    """Write a copy of the spectral XML with every R_* spectrum offset-corrected."""
    txt = open(in_path).read()
    offsets = []

    def repl(m):
        label, body = m.group(1), m.group(2)
        if not label.startswith('R_'):
            return m.group(0)
        arr = np.fromstring(body.replace('\n', ' '), sep=' ').reshape(-1, 2)
        off = estimate_offset(arr, r680_true)
        offsets.append(off)
        arr = correct(arr, off)
        lines = '\n'.join(f'\t\t{w:g} {v:.6f}' for w, v in arr)
        return f'<globaldata_vec2 label="{label}">\n{lines}\n\t</globaldata_vec2>'

    new = re.sub(r'<globaldata_vec2\s+label="([^"]+)"\s*>(.*?)</globaldata_vec2>',
                 repl, txt, flags=re.S)
    open(out_path, 'w').write(new)
    if report and offsets:
        o = np.array(offsets)
        print(f'corrected {len(o)} reflectance spectra; offset median {np.median(o):.4f} '
              f'p5 {np.percentile(o, 5):.4f} p95 {np.percentile(o, 95):.4f}')
    return np.array(offsets)


if __name__ == '__main__':
    import sys
    rewrite_xml(sys.argv[1], sys.argv[2])
