"""Per-species priors and inputs of the twin fit (block C, 2026-09-29).

The fit's algorithm (fit.fit_sparse, canopy.fit_closed, the site/age/seed/yaw search) is species-neutral; what a species
changes is the plant model (`canopy.species` in the config, see main.cpp) and the numbers the fit is given: the age
window it searches, the row and in-row spacing of the layout prior, how many leaflets make one leaf, the leaflet
filters of leaflets.py, and which vegetation mask reads the frame. Cowpea's entry is the set of values the code used
before this table existed, so a cowpea fit is unchanged.
"""

SPECIES = {
    "cowpea": dict(
        config="baseline.cfg",
        shoot_type="trifoliate",
        ages=(6, 8, 10, 12, 14, 16, 18, 20, 23, 26, 30, 35, 40, 46),   # fit.fit_sparse default
        stage1_ages=(5, 6, 7, 8, 9, 10, 11, 12, 14, 16, 18, 20, 23, 26, 30),   # stage1.AGES
        row_spacing_m=0.76, inrow_spacing_m=0.15,                        # scripts/twin_baseline_layout.py
        leaflets_per_leaf=3,
        leaflet_min_solidity=0.80, leaflet_max_plant_fraction=0.5,       # leaflets.py
        veg_mask="a_star",                                                # real.vegetation_mask
        row_pattern="single", paired_row_offset_m=0.0,                   # one row per detected row line
        layout_age=40.0,                                                  # canopy.row_layout default
        dap_range=(5, 46),
    ),
    "sorghum": dict(
        config="sorghum.cfg",
        shoot_type="mainstem",
        # days after planting; the synthetic benchmark spans 10-100 and the library plant has 16 nodes at 56 d
        ages=(8, 10, 13, 16, 20, 25, 30, 36, 43, 50, 60, 70, 80, 95),
        stage1_ages=(8, 10, 13, 16, 20, 25, 30, 36, 43, 50, 60),
        row_spacing_m=0.73, inrow_spacing_m=0.10,                        # T4 plots (preparation record); in-row assumed
        leaflets_per_leaf=1,                                              # one strap leaf per node
        leaflet_min_solidity=0.50,                                        # a curved strap leaf is not convex
        leaflet_max_plant_fraction=0.8,                                   # a young plant is two or three leaves
        veg_mask="exg",                                                   # the multi-crop package's ExG canopy mask
        row_pattern="single", paired_row_offset_m=0.0,
        layout_age=40.0,
        dap_range=(10, 100),
    ),
    # Tomato (T1-T6, 2026-09-29): the library tomato through config/tomato.cfg. Ages span the synthetic benchmark's DAP
    # range (params_tomato.json draws 10-90); the footprint keeps growing to about DAP 70 (the reference plants: canopy
    # radius 0.31 / 0.34 / 0.53 m at DAP 20 / 45 / 70), so the table is denser early. Layout: processing tomato on 1.5 m
    # (60 in) beds, single rows or paired rows 0.30 m apart on one bed, plants 0.30-0.60 m apart in the row (0.45 m);
    # the multi-crop generator's own field layout draws 0.5-1.0 m in-row and 1-2 planting rows. Leaves are compound, 7
    # leaflets per petiole; leaflet solidity measured on the twin's raster (median 0.90-0.94, DAP 20-70) keeps
    # cowpea's 0.80 filter.
    "tomato": dict(
        config="tomato.cfg",
        shoot_type="mainstem",
        ages=(10, 13, 16, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80, 90),
        stage1_ages=(10, 13, 16, 20, 25, 30, 35, 40, 45, 50, 60, 70),
        row_spacing_m=1.5, inrow_spacing_m=0.45,
        leaflets_per_leaf=7,
        leaflet_min_solidity=0.80, leaflet_max_plant_fraction=0.5,
        veg_mask="exg",
        row_pattern="single", paired_row_offset_m=0.30,                  # "paired": two rows 0.30 m apart per bed
        layout_age=45.0,
        dap_range=(10, 90),
    ),
}


def get(species="cowpea"):
    if species not in SPECIES:
        raise KeyError(f"unknown species {species!r}; known: {', '.join(SPECIES)}")
    return SPECIES[species]


def of_overrides(ov):
    """The species a set of config overrides names (canopy.species), cowpea when absent."""
    return str(ov.get("canopy.species", "cowpea"))


def leaves_from_leaflets(n_leaflets, species="cowpea"):
    """Compound leaves that `n_leaflets` visible leaflet objects make (3 per cowpea trifoliate, 7 per tomato leaf, 1 per
    sorghum blade); the rasterizer's object map numbers leaflets, not leaves."""
    return float(n_leaflets) / get(species)["leaflets_per_leaf"]

