"""Figures for the Tier-2 section: mAP by condition, and proxy rank against mAP rank."""
import json

W, H, L, R, T, B = 680, 210, 132, 20, 22, 40

TIER2 = [("Real only (ceiling)", 0.8793, None, "s1"),
         ("v17", 0.3652, 0.0264, "s3"),
         ("synthetic_final", 0.3140, 0.0075, "s3"),
         ("Baseline, 1307 tiles", 0.2933, None, "s2"),
         ("Baseline, 120 tiles", 0.2914, 0.0687, "s2")]

# (name, KID, objective, mAP50) -- lower KID and lower objective are "better" by design.
PROXIES = [("Baseline", 29.24, 0.454, 0.2914),
           ("synthetic_final", 50.60, 0.577, 0.3140),
           ("v17", 54.40, 0.549, 0.3652)]


def bars():
    xmax = 1.0
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Detection mAP at 0.5 IoU on held-out real imagery, by training set">',
           '<g class="grid">']
    for t in (0, 0.2, 0.4, 0.6, 0.8, 1.0):
        x = L + t / xmax * (W - L - R)
        out.append(f'<line x1="{x:.1f}" y1="{T}" x2="{x:.1f}" y2="{H-B}"/>')
        out.append(f'<text class="tick" x="{x:.1f}" y="{H-B+16}" text-anchor="middle">{t:.1f}</text>')
    out.append("</g>")
    row_h = (H - T - B) / len(TIER2)
    for i, (name, val, err, cls) in enumerate(TIER2):
        y = T + row_h * (i + 0.5)
        x = L + val / xmax * (W - L - R)
        out.append(f'<text class="rowlab" x="{L-10}" y="{y+4}" text-anchor="end">{name}</text>')
        out.append(f'<rect class="{cls}" fill="var(--{cls})" x="{L}" y="{y-7:.1f}" width="{x-L:.1f}" height="14" rx="3" opacity="0.85"/>')
        if err:
            e0 = L + max(0.0, val - err) / xmax * (W - L - R)
            e1 = L + (val + err) / xmax * (W - L - R)
            out.append(f'<line class="axis" x1="{e0:.1f}" y1="{y:.1f}" x2="{e1:.1f}" y2="{y:.1f}" stroke-width="1.5"/>')
        out.append(f'<text class="val {cls}t" x="{x+8:.1f}" y="{y+4:.1f}">{val:.3f}</text>')
    out.append(f'<text class="axlab" x="{W-R}" y="{H-6}" text-anchor="end">mAP@50 on held-out real tiles</text>')
    out.append("</svg>")
    return "\n".join(out)


def proxy_scatter():
    """Each proxy's ranking against the measured ranking. A good proxy is monotone; both are not."""
    PH = 220
    out = [f'<svg viewBox="0 0 {W} {PH}" role="img" aria-label="KID and the asymmetric objective plotted against measured mAP for three training sets">']
    panels = [("KID (lower = better)", [p[1] for p in PROXIES], "s2"),
              ("Asymmetric objective (lower = better)", [p[2] for p in PROXIES], "s3")]
    pw = (W - 40) / 2
    for pi, (title, vals, cls) in enumerate(panels):
        ox = 20 + pi * pw
        x0, x1 = ox + 52, ox + pw - 18
        y0, y1 = PH - 46, 40
        vmin, vmax = min(vals), max(vals)
        mmin, mmax = min(p[3] for p in PROXIES), max(p[3] for p in PROXIES)
        pad = lambda lo, hi: (lo - 0.18 * (hi - lo), hi + 0.18 * (hi - lo))
        vmin, vmax = pad(vmin, vmax); mmin, mmax = pad(mmin, mmax)
        out.append(f'<text class="rowlab" x="{ox+52}" y="{26}">{title}</text>')
        out.append(f'<line class="axis" x1="{x0}" y1="{y0}" x2="{x1}" y2="{y0}"/>')
        out.append(f'<line class="axis" x1="{x0}" y1="{y0}" x2="{x0}" y2="{y1}"/>')
        pts = []
        for (name, kid, obj, m), v in zip(PROXIES, vals):
            px = x0 + (v - vmin) / (vmax - vmin) * (x1 - x0)
            py = y0 - (m - mmin) / (mmax - mmin) * (y0 - y1)
            pts.append((px, py, name))
        d = "M" + " L".join(f"{p[0]:.1f},{p[1]:.1f}" for p in sorted(pts))
        out.append(f'<path class="ln {cls}" d="{d}" opacity="0.55" stroke-dasharray="4 3"/>')
        for px, py, name in pts:
            out.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="5" fill="var(--{cls})"/>')
            out.append(f'<text class="tick" x="{px:.1f}" y="{py-11:.1f}" text-anchor="middle">{name}</text>')
        out.append(f'<text class="axlab" x="{x0-8}" y="{y1+4}" text-anchor="end">mAP</text>')
    out.append("</svg>")
    return "\n".join(out)


if __name__ == "__main__":
    json.dump({"tier2_bars": bars(), "proxy_scatter": proxy_scatter()},
              open("audit/figs_tier2.json", "w"))
    print("wrote audit/figs_tier2.json")
