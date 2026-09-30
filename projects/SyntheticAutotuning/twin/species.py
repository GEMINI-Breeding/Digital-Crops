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
    ),
    # Tomato (2026-09-29): compound leaves of 7 leaflets per petiole (PlantLibrary.cpp initializeTomatoShoots); leaflet
    # solidity measured on the twin's raster (median 0.90-0.94 at DAP 20-70) keeps cowpea's 0.80 filter.
    "tomato": dict(
        config="tomato.cfg",
        shoot_type="mainstem",
        ages=(10, 15, 20, 25, 30, 35, 40, 50, 60, 70, 80, 90),
        stage1_ages=(10, 15, 20, 25, 30, 35, 40, 50),
        row_spacing_m=1.5, inrow_spacing_m=0.45,
        leaflets_per_leaf=7,
        leaflet_min_solidity=0.80, leaflet_max_plant_fraction=0.5,
        veg_mask="exg",
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

