"""Single-image digital twin: fit the Helios cowpea generator to ONE real T4 rover frame.

The sibling package `syn2real` fits a *distribution* of synthetic images to a *set* of real
tiles. This package fits one scene to one frame: plant positions are taken from the photo,
each plant carries its own random stream (see `canopy.per_plant_seed` in main.cpp), and the
fit proceeds in stages -- camera, layout, per-plant realisation, appearance -- each evaluated
against the real frame with the cheapest instrument that can see the difference.
"""
