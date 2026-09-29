"""Figures for the proxy-validation, label-convention and object-size results."""
import json, numpy as np

W, H, L, R, T, B = 680, 250, 62, 20, 26, 44


def _axes(out, xs, xlabel, xticks, ylo, yhi, yticks):
    for t in xticks:
        x = L + (t - xs[0]) / (xs[1] - xs[0]) * (W - L - R)
        out.append(f'<line class="gridline" x1="{x:.1f}" y1="{T}" x2="{x:.1f}" y2="{H-B}"/>')
        out.append(f'<text class="tick" x="{x:.1f}" y="{H-B+16}" text-anchor="middle">{t:g}</text>')
    for t in yticks:
        y = H - B - (t - ylo) / (yhi - ylo) * (H - T - B)
        out.append(f'<text class="tick" x="{L-8}" y="{y+4:.1f}" text-anchor="end">{t:g}</text>')
    out.append(f'<line class="axis" x1="{L}" y1="{H-B}" x2="{W-R}" y2="{H-B}"/>')
    out.append(f'<line class="axis" x1="{L}" y1="{H-B}" x2="{L}" y2="{T}"/>')
    out.append(f'<text class="axlab" x="{W-R}" y="{H-6}" text-anchor="end">{xlabel}</text>')
    out.append(f'<text class="axlab" x="{L-8}" y="{T-8}" text-anchor="end">mAP</text>')


def scatter(points, xs, xlabel, xticks, cls, aria, ylo=0.0, yhi=0.45, yticks=(0.1,0.2,0.3,0.4), line=False):
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{aria}"><g class="grid">']
    _axes(out, xs, xlabel, xticks, ylo, yhi, yticks)
    out.append("</g>")
    px = [(L + (x - xs[0]) / (xs[1] - xs[0]) * (W - L - R),
           H - B - (y - ylo) / (yhi - ylo) * (H - T - B), lab) for x, y, lab in points]
    if line:
        out.append(f'<path class="ln {cls}" d="M' + " L".join(f"{a:.1f},{b:.1f}" for a, b, _ in px) + '"/>')
    for a, b, lab in px:
        out.append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="5" fill="var(--{cls})"/>')
        if lab:
            out.append(f'<text class="tick" x="{a:.1f}" y="{b-11:.1f}" text-anchor="middle">{lab}</text>')
    out.append("</svg>")
    return "\n".join(out)


if __name__ == "__main__":
    figs = {}
    # Proxy against mAP: eight configs, diverse by construction.
    val = json.load(open("audit/tier2_val.json")); cfg = json.load(open("audit/validation_configs.json"))
    pts = []
    for k in sorted(val):
        n = k.replace("synthetic_", "")
        pts.append((cfg[n]["proxy"], float(np.mean([r["mAP50"] for r in val[k]])), n))
    figs["proxy"] = scatter(sorted(pts), (0, 5.4), "asymmetric objective score (lower = better match)",
                            (0, 1, 2, 3, 4, 5), "s2",
                            "Proxy objective against measured mAP for eight diverse configurations")
    # Label convention on identical imagery.
    lab = json.load(open("audit/tier2_label.json")); meta = json.load(open("audit/label_variants.json"))
    order = ["all", "min15", "min23", "min35", "min45"]
    pts = [(meta[k]["min_box_px"], float(np.mean([r["mAP50"] for r in lab[f"synthetic_lab_{k}"]])), k)
           for k in order]
    figs["label"] = scatter(pts, (0, 46), "minimum labelled box size, tile px", (0, 10, 20, 30, 40),
                            "s3", "Detection mAP against labelling threshold, identical images", line=True)
    # Object size sweep.
    sz = json.load(open("audit/tier2_size.json")); ss = json.load(open("audit/size_sets.json"))
    pts = []
    for k in sorted(sz):
        n = k.replace("synthetic_", "")
        pts.append((ss[n]["boxes_per_tile"], float(np.mean([r["mAP50"] for r in sz[k]])), n.replace("size", "")))
    figs["size"] = scatter(sorted(pts), (2, 8), "labelled objects per tile", (2, 4, 6, 8), "s1",
                           "Detection mAP against labelled object density", line=True)
    json.dump(figs, open("audit/figs15.json", "w"))
    print("wrote", ", ".join(figs))
