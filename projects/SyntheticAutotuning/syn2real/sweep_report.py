"""Summarize a geometry sweep against the real label statistics.

Reads every run under a sweep directory, pools the boxes for each parameter setting across seeds,
and reports the statistics that the real annotations can be compared against directly.
"""

from __future__ import annotations

import glob
import os
import re

import numpy as np

from .geom_io import read_boxes

#: Measured from projects/SyntheticAutotuning/real, 1991 boxes over 263 tiles.
REAL = dict(size_p50=33.0, size_p95=48.8, aspect_p50=1.04, frac_narrow=0.123)


def pool(tag_dir, classes=("flower_open", "flower_closed")):
    """Concatenate the boxes of every seed under one parameter setting."""
    runs = sorted(glob.glob(os.path.join(tag_dir, "geom_*")))
    parts = []
    for run in runs:
        try:
            boxes = read_boxes(run)
        except FileNotFoundError:
            continue
        if len(boxes):
            parts.append(boxes[np.isin(boxes["name"], classes)])
    if not parts:
        return None
    return np.concatenate(parts), len(runs)


def summarize_sweep(sweep_dir, classes=("flower_open", "flower_closed")):
    """Return one row per parameter setting, sorted by how far it sits from the real statistics."""
    rows = []
    for tag_dir in sorted(glob.glob(os.path.join(sweep_dir, "*"))):
        if not os.path.isdir(tag_dir):
            continue
        pooled = pool(tag_dir, classes)
        if pooled is None:
            continue
        boxes, n_runs = pooled
        if len(boxes) == 0:
            continue
        row = dict(
            tag=os.path.basename(tag_dir),
            n_runs=n_runs,
            n_boxes=int(len(boxes)),
            size_p50=float(np.median(boxes["size"])),
            size_p95=float(np.percentile(boxes["size"], 95)),
            aspect_p50=float(np.median(boxes["aspect"])),
            frac_narrow=float(np.mean(boxes["aspect"] < 0.6)),
        )
        # Normalized distance from the real statistics. Size terms are divided by the real value so
        # they are relative errors; the aspect and narrow-fraction terms are already dimensionless.
        row["error"] = (
            abs(row["size_p50"] - REAL["size_p50"]) / REAL["size_p50"]
            + abs(row["size_p95"] - REAL["size_p95"]) / REAL["size_p95"]
            + abs(row["aspect_p50"] - REAL["aspect_p50"])
            + abs(row["frac_narrow"] - REAL["frac_narrow"])
        ) / 4.0
        rows.append(row)
    return sorted(rows, key=lambda r: r["error"])


def render_table(rows):
    header = f"{'setting':16s} {'runs':>4s} {'boxes':>6s} {'size p50':>9s} {'size p95':>9s} {'aspect':>7s} {'narrow%':>8s} {'error':>7s}"
    lines = [header, "-" * len(header)]
    for r in rows:
        lines.append(
            f"{r['tag']:16s} {r['n_runs']:4d} {r['n_boxes']:6d} {r['size_p50']:9.1f} {r['size_p95']:9.1f} "
            f"{r['aspect_p50']:7.2f} {r['frac_narrow']*100:7.1f}% {r['error']:7.3f}"
        )
    lines.append(
        f"{'REAL':16s} {'':4s} {1991:6d} {REAL['size_p50']:9.1f} {REAL['size_p95']:9.1f} "
        f"{REAL['aspect_p50']:7.2f} {REAL['frac_narrow']*100:7.1f}% {0.0:7.3f}"
    )
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    print(render_table(summarize_sweep(sys.argv[1] if len(sys.argv) > 1 else "geom_sweep")))
