"""Build the distribution SVGs for report section 12.

The report had been reporting medians, which is what let a bimodal mixture pass as a match. These
draw the whole distribution instead, in the report's own chart idiom: teal for real, amber for the
build being corrected, violet for the corrected build.
"""
import json, os, sys

W, H = 680, 232
L, R, T, B = 52, 14, 22, 44          # margins
SERIES = [("real", "s1", "Real"), ("prev", "s2", "Previous build"), ("v17", "s3", "v17")]


def _poly(vals, bins, xlo, xhi, ymax):
    """Histogram counts -> a normalized density polyline across the plot box."""
    total = sum(vals) or 1
    pts = []
    for i, v in enumerate(vals):
        xc = 0.5 * (bins[i] + bins[i + 1])
        x = L + (xc - xlo) / (xhi - xlo) * (W - L - R)
        y = H - B - (v / total) / ymax * (H - T - B)
        pts.append((x, y))
    return pts


def chart(dat, key, bins_key, xlo, xhi, xticks, xlabel, aria, marks=None):
    bins = dat[bins_key]
    series = []
    ymax = 0.0
    for name, cls, label in SERIES:
        vals = dat[name][key]
        total = sum(vals) or 1
        ymax = max(ymax, max(v / total for v in vals))
        series.append((name, cls, label, vals))
    ymax *= 1.15

    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{aria}">', '<g class="grid">']
    for t in xticks:
        x = L + (t - xlo) / (xhi - xlo) * (W - L - R)
        out.append(f'<line x1="{x:.1f}" y1="{T}" x2="{x:.1f}" y2="{H-B}"/>')
        lbl = f"{t:g}"
        out.append(f'<text class="tick" x="{x:.1f}" y="{H-B+16}" text-anchor="middle">{lbl}</text>')
    out.append("</g>")
    out.append(f'<line class="axis" x1="{L}" y1="{H-B}" x2="{W-R}" y2="{H-B}"/>')

    for name, cls, label, vals in series:
        pts = _poly(vals, bins, xlo, xhi, ymax)
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        out.append(f'<path class="ln {cls}" d="{d}"/>')

    for mark in marks or []:
        x = L + (mark["at"] - xlo) / (xhi - xlo) * (W - L - R)
        out.append(f'<line class="mark" x1="{x:.1f}" y1="{T}" x2="{x:.1f}" y2="{H-B}"/>')
        out.append(f'<text class="tick" x="{x:.1f}" y="{T-6}" text-anchor="middle">{mark["label"]}</text>')

    lx = L + 6
    for name, cls, label, _ in series:
        out.append(f'<line class="ln {cls}" x1="{lx}" y1="{H-10}" x2="{lx+18}" y2="{H-10}"/>')
        out.append(f'<text class="tick {cls}t" x="{lx+23}" y="{H-6}">{label}</text>')
        lx += 34 + 7.0 * len(label)
    out.append(f'<text class="axlab" x="{W-R}" y="{H-6}" text-anchor="end">{xlabel}</text>')
    out.append("</svg>")
    return "\n".join(out)


def granulo_chart(g):
    radii = g["radii"]
    xlo, xhi = radii[0], radii[-1]
    ymax = max(max(g[n]["spec"]) for n, _, _ in SERIES if n in g) * 1.15
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" '
           f'aria-label="Morphological pattern spectrum, real against synthetic, out to leaf scale">',
           '<g class="grid">']
    for t in [0, 25, 50, 75, 100, 120]:
        x = L + (t - xlo) / (xhi - xlo) * (W - L - R)
        out.append(f'<line x1="{x:.1f}" y1="{T}" x2="{x:.1f}" y2="{H-B}"/>')
        out.append(f'<text class="tick" x="{x:.1f}" y="{H-B+16}" text-anchor="middle">{t}</text>')
    out.append("</g>")
    out.append(f'<line class="axis" x1="{L}" y1="{H-B}" x2="{W-R}" y2="{H-B}"/>')
    for name, cls, label in SERIES:
        if name not in g:
            continue
        pts = []
        for r, v in zip(radii, g[name]["spec"]):
            x = L + (r - xlo) / (xhi - xlo) * (W - L - R)
            y = H - B - v / ymax * (H - T - B)
            pts.append((x, y))
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        out.append(f'<path class="ln {cls}" d="{d}"/>')
    lx = L + 6
    for name, cls, label in SERIES:
        if name not in g:
            continue
        out.append(f'<line class="ln {cls}" x1="{lx}" y1="{H-10}" x2="{lx+18}" y2="{H-10}"/>')
        out.append(f'<text class="tick {cls}t" x="{lx+23}" y="{H-6}">{label}</text>')
        lx += 34 + 7.0 * len(label)
    out.append(f'<text class="axlab" x="{W-R}" y="{H-6}" text-anchor="end">structure radius, tile px</text>')
    out.append("</svg>")
    return "\n".join(out)


if __name__ == "__main__":
    d = json.load(open("audit/dist_v17.json"))
    figs = {
        "size": chart(d, "size_hist", "size_bins", 10, 86, [10, 20, 30, 40, 50, 60, 70, 80],
                      "object size &radic;(w&middot;h), tile px",
                      "Distribution of labelled object size, real against synthetic",
                      marks=[{"at": 23.4, "label": "min-box filter"}]),
        "aspect": chart(d, "logasp_hist", "asp_bins", -2, 2, [-2, -1, 0, 1, 2],
                        "log aspect ratio, log(w/h)",
                        "Distribution of log aspect ratio, real against synthetic",
                        marks=[{"at": 0.0, "label": "square"}]),
        "per": chart(d, "per_hist", "per_bins", 0, 25, [0, 5, 10, 15, 20, 25],
                     "labelled objects per tile",
                     "Distribution of labelled objects per tile, real against synthetic"),
    }
    if os.path.exists("audit/granulo_v17.json"):
        figs["granulo"] = granulo_chart(json.load(open("audit/granulo_v17.json")))
    json.dump(figs, open("audit/figs_v17.json", "w"))
    print("wrote", ", ".join(figs))
