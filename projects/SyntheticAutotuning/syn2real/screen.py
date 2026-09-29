"""Phase 4: Morris elementary-effects screening over scene and architecture parameters.

Every parameter in this project so far was chosen by looking at one statistic at a time and
adjusting one knob. That produced five dataset versions, a best-to-worst spread of 0.10 mAP, and
three cases where the knob turned out to be compensating for a measurement error rather than a
model error. Screening exists to replace that: vary everything at once over its plausible range,
and rank parameters by how much they actually move the outputs.

The response vector is deliberately the label and structure statistics that the rasterized pass can
produce in ~20 s, not appearance -- appearance needs the ray tracer, and the Tier-2 matrix has so
far shown appearance fidelity buying nothing measurable in detection.

Morris is used rather than Sobol because it costs (d+1) x r runs instead of thousands, which is what
makes a 12-parameter screen affordable at all. It ranks; it does not quantify interactions. Sobol on
the survivors is the follow-up the plan calls for.
"""

from __future__ import annotations

import numpy as np

#: Parameter ranges. Bounds are plausible-physical, not the current values +/- a bit: the point of a
#: screen is to find out what matters across the space, not to confirm a local guess.
PROBLEM = {
    "names": [
        "canopy.germination_fraction_min",
        "canopy.plant_spacing_y",
        "canopy.age",
        "leaf.prototype_scale_min",
        "leaf.prototype_scale_max",
        "flower.prototype_scale",
        "flower.closed_scale",
        "flower.bud_break_prob_min",
        "flower.inflorescence_pitch_max",
        "flower.peduncle_length_max",
        "phenology.time_to_flower_initiation",
        "phenology.time_to_flower_opening",
    ],
    "bounds": [
        [0.20, 0.90],    # germination fraction
        [0.07, 0.18],    # within-row plant spacing, m
        [30, 50],        # growth days at imaging
        [0.07, 0.12],    # leaflet length lower bound, m
        [0.12, 0.20],    # leaflet length upper bound, m
        [0.020, 0.045],  # open corolla prototype scale, m
        [1.0, 2.5],      # bud size relative to corolla
        [0.05, 0.45],    # flower bud break probability
        [50, 95],        # inflorescence pitch upper bound, deg
        [0.15, 0.40],    # peduncle length upper bound, m
        [12, 26],        # days to flower initiation
        [2, 8],          # days a bud stays closed
    ],
    "num_vars": 12,
}

#: Statistics the screen ranks against, all from the rasterized annotations.
OUTPUTS = ["cover", "boxes_per_frame", "size_p50", "size_p95", "log_aspect_med", "nn_spacing"]

#: Real targets, so effects can be reported in units of "fraction of the real value".
#: Recomputed from all 263 real tiles for Appendix A; several were previously a 40-tile draw whose
#: seed-to-seed spread was larger than the differences being optimised against them.
REAL = dict(cover=0.927, boxes_per_frame=24.2, size_p50=33.002, size_p95=48.799,
            log_aspect_med=0.0408, nn_spacing=69.453, granulo_mean_r=38.7)

INT_PARAMS = {"canopy.age", "phenology.time_to_flower_initiation", "phenology.time_to_flower_opening"}


def sample(trajectories=8, seed=0):
    """Morris trajectories. Cost is (num_vars + 1) * trajectories runs."""
    from SALib.sample import morris as morris_sample
    X = morris_sample.sample(PROBLEM, N=trajectories, num_levels=4, seed=seed)
    return X


def to_overrides(row):
    """One sampled row -> config key/value overrides for the geom binary."""
    out = {}
    for name, value in zip(PROBLEM["names"], row):
        out[name] = str(int(round(value))) if name in INT_PARAMS else f"{value:.4f}"
    # Several parameters are min/max PAIRS that the renderer samples between, and Morris varies one
    # member of the pair. Overriding only that member leaves the other at its config value, which
    # inverts the range for much of the design and makes the renderer refuse the run. In the first
    # attempt that killed 100 of 104 runs, and because return codes were not checked the screen
    # still produced a ranked table -- from four surviving points.
    #
    # Every pair is therefore written as a pair: the sampled value sets one bound and the other
    # follows it, preserving the width the config was calibrated with.
    lo, hi = float(out["leaf.prototype_scale_min"]), float(out["leaf.prototype_scale_max"])
    if hi <= lo:
        out["leaf.prototype_scale_max"] = f"{lo + 0.03:.4f}"

    # Germination is drawn per scene; collapse it so the draw is not noise on the design.
    out["canopy.germination_fraction_max"] = out["canopy.germination_fraction_min"]

    # Bud-break probability: sampled value is the lower bound, keep the config width of 0.05.
    bud_lo = float(out["flower.bud_break_prob_min"])
    out["flower.bud_break_prob_max"] = f"{bud_lo + 0.05:.4f}"

    # Peduncle length: sampled value is the upper bound, keep the config width of 0.05.
    ped_hi = float(out["flower.peduncle_length_max"])
    out["flower.peduncle_length_min"] = f"{max(0.05, ped_hi - 0.05):.4f}"

    # Inflorescence pitch: sampled value is the upper bound, keep the config width of 20 deg.
    pitch_hi = float(out["flower.inflorescence_pitch_max"])
    out["flower.inflorescence_pitch_min"] = f"{max(0.0, pitch_hi - 20.0):.4f}"
    return out


def analyze(X, Y, output_name):
    """Morris mu* and sigma for one output, as a ranked table."""
    from SALib.analyze import morris as morris_analyze
    res = morris_analyze.analyze(PROBLEM, X, np.asarray(Y), num_levels=4, print_to_console=False)
    order = np.argsort(-np.asarray(res["mu_star"]))
    rows = [(PROBLEM["names"][i], float(res["mu_star"][i]), float(res["sigma"][i])) for i in order]
    return rows
