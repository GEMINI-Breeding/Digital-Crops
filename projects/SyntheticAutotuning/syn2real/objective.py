"""The asymmetric objective: score coverage of the real distribution, not agreement of medians.

Every regression found in this project so far was a spread error that a centre statistic could not
see. Flower size p50 matched while p95 was 8 px short; isotropy matched while nearest-neighbour
spacing was 70% too large; structure radius matched while canopy cover had no sparse tail at all.
Selecting on medians is what let all three through.

The objective follows the project plan: a synthetic distribution *wider* than the real one costs
nothing, because extra variability is cheap insurance for a detector, while one that is narrower or
shifted leaves real modes the detector never sees. Concretely, per statistic:

    coverage deficit  =  fraction of the real [p5, p95] interval not spanned by the synthetic one
    centring          =  |median difference| / real IQR,  weighted weakly

and the total is their weighted sum. A synthetic interval that strictly contains the real one scores
zero on both terms regardless of how much wider it is.
"""

from __future__ import annotations

import numpy as np

#: Weight on the centring term relative to coverage. Deliberately small: the plan's whole point is
#: that being off-centre is a milder failure than failing to reach a real mode.
LAMBDA_CENTRE = 0.25


def coverage_deficit(real, syn):
    """Fraction of the real p5-p95 interval that the synthetic p5-p95 interval fails to cover."""
    r_lo, r_hi = np.percentile(real, 5), np.percentile(real, 95)
    s_lo, s_hi = np.percentile(syn, 5), np.percentile(syn, 95)
    span = r_hi - r_lo
    if span <= 0:
        return 0.0
    covered = max(0.0, min(r_hi, s_hi) - max(r_lo, s_lo))
    return float(1.0 - covered / span)


def centring_error(real, syn):
    """Median offset in units of the real IQR."""
    iqr = np.percentile(real, 75) - np.percentile(real, 25)
    if iqr <= 0:
        return 0.0
    return float(abs(np.median(syn) - np.median(real)) / iqr)


def score_statistic(real, syn):
    """Both terms plus the combined score for one statistic."""
    deficit = coverage_deficit(real, syn)
    centre = centring_error(real, syn)
    return dict(coverage_deficit=deficit, centring=centre,
                score=deficit + LAMBDA_CENTRE * centre,
                real_p5=float(np.percentile(real, 5)), real_p95=float(np.percentile(real, 95)),
                syn_p5=float(np.percentile(syn, 5)), syn_p95=float(np.percentile(syn, 95)))


def score(real_stats, syn_stats, weights=None):
    """Score every statistic present in both, returning per-statistic rows and the weighted total.

    `real_stats` and `syn_stats` map a statistic name to a 1-D sample of its values.
    """
    names = [k for k in real_stats if k in syn_stats]
    if not names:
        raise ValueError("no statistics in common between the real and synthetic sets")
    weights = weights or {}
    rows, total, wsum = {}, 0.0, 0.0
    for name in names:
        row = score_statistic(np.asarray(real_stats[name]), np.asarray(syn_stats[name]))
        w = float(weights.get(name, 1.0))
        rows[name] = row
        total += w * row["score"]
        wsum += w
    return rows, total / wsum


def verdict(row, narrow_tol=0.10, centre_tol=0.5):
    """Human-readable grade, matching the vocabulary used elsewhere in this project."""
    if row["coverage_deficit"] > narrow_tol and row["centring"] > centre_tol:
        return "SHIFTED"
    if row["coverage_deficit"] > narrow_tol:
        return "TOO-NARROW"
    if row["centring"] > centre_tol:
        return "OFF-CENTRE"
    if row["syn_p95"] - row["syn_p5"] > 1.25 * (row["real_p95"] - row["real_p5"]):
        return "WIDER-OK"
    return "OK"


def render_table(rows, total):
    header = f"{'statistic':22s} {'real p5-p95':>17s} {'syn p5-p95':>17s} {'deficit':>8s} {'centre':>7s}  verdict"
    lines = [header, "-" * len(header)]
    for name, row in sorted(rows.items(), key=lambda kv: -kv[1]["score"]):
        lines.append(
            f"{name:22s} {row['real_p5']:8.2f}-{row['real_p95']:8.2f} "
            f"{row['syn_p5']:8.2f}-{row['syn_p95']:8.2f} "
            f"{row['coverage_deficit']:8.2f} {row['centring']:7.2f}  {verdict(row)}"
        )
    lines.append("-" * len(header))
    lines.append(f"{'WEIGHTED TOTAL':22s} {total:56.3f}")
    return "\n".join(lines)
