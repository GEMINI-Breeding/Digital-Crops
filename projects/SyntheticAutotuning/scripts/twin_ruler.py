"""Leaflet and petiole size measured from the geometry, the way a hand label measures it.

main.cpp's diag.leafruler writes every leaflet's base, tip and two widest points as world coordinates, and
diag.stalkdump writes both ends of every petiole; this projects them through the camera, so an organ half
hidden behind another still measures its full length. That is the difference from
twin.leaflets.synthetic_leaflets, which measures connected components of *visible* leaf pixels and therefore
reads short in dense canopies -- it put the 06-20 Plot286 twin at 46 mm where hand labels of the same render
measure 61.8 mm.

A hand label is only placed on an organ the labeller can follow end to end, so the population median is the
wrong thing to compare against one: the twin's population includes every half-expanded organ buried in the
canopy centre, and the labels cannot. Organs are therefore scored by how much of their axis the camera
actually sees -- the fraction of samples along base->tip whose pixel in the object map belongs to that organ
-- and the comparison is made visible-to-visible. Axis traceability, not visible area: a leaflet can show 60%
of its area with its tip buried, and area fraction then reads it as measurable when a labeller could not
place the line.

Reported per frame, against the hand labels in twin_work/labels:
  projected   pixel length x 0.783 mm/px, the labelling convention (organs assumed at 0.154 m)
  true        the 3D length of the same base-to-tip segment

usage: twin_ruler.py --workdir twin_work/<frame>_final [--overrides ov.json] [--min-traceable 0.7]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np  # noqa: E402

import twin.raster as TR  # noqa: E402
import twin.real as R  # noqa: E402

MM_PER_PX_LABEL = 0.783  # the labelling scale: camera height 1.55355 m, leaves assumed at 0.154 m
PETIOLULE_MM = 5.0  # a "petiole" this short is a petiolule stub, not an organ anybody labels

ap = argparse.ArgumentParser()
ap.add_argument("--workdir", required=True, help="fit workdir holding layout.txt and fit.json")
ap.add_argument("--overrides", default=None, help="JSON of generator overrides (default: the workdir's fit.json)")
ap.add_argument("--min-traceable", type=float, default=0.7)
ap.add_argument("--json", default=None, help="write the per-organ table here")
ap.add_argument("--binary", default=None, help="rasterizer binary (default: twin.raster.BINARY)")
a = ap.parse_args()

work = os.path.abspath(a.workdir)
ov = json.load(open(a.overrides)) if a.overrides else json.load(open(os.path.join(work, "fit.json")))["overrides"]
ov = dict(ov.get("best_overrides", ov))
ruler_path = os.path.join(work, "leafruler.txt")
stalk_path = os.path.join(work, "stalkdump.txt")
ov.update({"canopy.layout_file": os.path.join(work, "layout.txt"), "diag.leafruler": ruler_path,
           "diag.stalkdump": stalk_path, "raster.split_stems": 1})

maps = TR.run(ov, folder=os.path.join(work, "ruler"), base="ruler", binary=a.binary or TR.BINARY)
scale = float(ov.get("raster.scale", 1.0))
# A render ov.json carries only what differs from the render script's own command line, so the camera can be
# missing from it; the workdir's fit.json always has the camera the layout was fitted under.
fitted = json.load(open(os.path.join(work, "fit.json")))["overrides"]
height_m = float(ov.get("camera.height", fitted["camera.height"]))
hfov_deg = float(ov.get("camera.hfov", fitted["camera.hfov"]))
fx = 0.5 * R.WIDTH / np.tan(np.radians(0.5 * hfov_deg))


def project(p):
    """World metres -> full-resolution pixel. The camera looks straight down from height_m over the origin."""
    depth = height_m - p[:, 2]
    return np.stack([R.WIDTH / 2.0 + p[:, 0] * fx / depth, R.HEIGHT / 2.0 - p[:, 1] * fx / depth], axis=1)


# The map numbers organs in rasterization order, so the binary writes <base>_objindex.txt beside the maps
# giving each Helios object ID's number; joining through it is exact, where a point-in-surface test against
# the depth map is not -- the blade is curved, so planar samples miss it, and they miss the large leaflets
# most, which is the opposite of the bias we are trying to measure.
obj_map = maps.obj
map_h, map_w = obj_map.shape
index_of = {}
for line in open(os.path.join(work, "ruler", "ruler_objindex.txt")):
    if not line.startswith("#"):
        helios_id, organ_index = line.split()
        index_of[int(helios_id)] = int(organ_index)

AXIS_SAMPLES = np.linspace(0.05, 0.95, 40)


def traceable(obj_ids, end_a, end_b, neighbourhood=0):
    """Fraction of each organ's axis the camera sees. A petiole rasterizes about one pixel wide, so an axis
    sample can round onto a neighbouring pixel and read as hidden when it is plainly in view; passing
    neighbourhood=1 accepts the 3x3 around the sample, which a blade (tens of pixels across) does not need."""
    out = np.zeros(len(obj_ids))
    offsets = range(-neighbourhood, neighbourhood + 1)
    for k in range(len(obj_ids)):
        pts = end_a[k][None, :] + AXIS_SAMPLES[:, None] * (end_b[k] - end_a[k])[None, :]
        q = project(pts) * scale
        xi, yi = q[:, 0].astype(int), q[:, 1].astype(int)
        mine = index_of.get(int(obj_ids[k]), -1)
        hit = np.zeros(len(xi), bool)
        for dx in offsets:
            for dy in offsets:
                hit |= obj_map[np.clip(yi + dy, 0, map_h - 1), np.clip(xi + dx, 0, map_w - 1)] == mine
        out[k] = hit.mean()
    return out


def report(name, obj_ids, plant, end_a, end_b, wide_a=None, wide_b=None, neighbourhood=0):
    length_true = np.linalg.norm(end_b - end_a, axis=1) * 1000.0
    length_px = np.linalg.norm(project(end_b) - project(end_a), axis=1)
    trace = traceable(obj_ids, end_a, end_b, neighbourhood)
    keep = trace >= a.min_traceable
    print(f"\n{name}: {len(obj_ids)} organs, {int(keep.sum())} with at least {a.min_traceable:.0%} of the axis "
          f"in view ({len(np.unique(plant))} plants)")
    rows = [("projected mm", length_px * MM_PER_PX_LABEL), ("true length mm", length_true)]
    if wide_a is not None:
        rows.insert(1, ("projected width mm", np.linalg.norm(project(wide_b) - project(wide_a), axis=1) * MM_PER_PX_LABEL))
        rows.append(("true width mm", np.linalg.norm(wide_b - wide_a, axis=1) * 1000.0))
    for label, v in rows:
        print(f"  {label:20s} population {np.median(v):6.1f}   traceable {np.median(v[keep]):6.1f}"
              f"  (p25 {np.percentile(v[keep], 25):5.1f}  p75 {np.percentile(v[keep], 75):5.1f})")
    ratio = np.median(length_px[keep]) / np.median(length_px)
    print(f"  traceable/population length ratio {ratio:.2f}x")
    return dict(n=len(obj_ids), n_traceable=int(keep.sum()),
                projected_mm=float(np.median(length_px[keep]) * MM_PER_PX_LABEL),
                projected_population_mm=float(np.median(length_px) * MM_PER_PX_LABEL),
                true_mm=float(np.median(length_true[keep])), ratio=float(ratio))


rows = np.loadtxt(ruler_path, comments="#")
if rows.ndim == 1:
    rows = rows[None, :]
leaf = report("LEAFLETS", rows[:, 1].astype(int), rows[:, 0].astype(int),
              rows[:, 3:6], rows[:, 6:9], rows[:, 9:12], rows[:, 12:15])

stalks = [line.split() for line in open(stalk_path) if not line.startswith("#")]
stalks = [s for s in stalks if s[0] == "petiole"]
pet_obj = np.array([int(s[2]) for s in stalks])
pet_plant = np.array([int(s[1]) for s in stalks])
pet_a = np.array([[float(x) for x in s[3:6]] for s in stalks])
pet_b = np.array([[float(x) for x in s[6:9]] for s in stalks])
long_enough = np.linalg.norm(pet_b - pet_a, axis=1) * 1000.0 >= PETIOLULE_MM
print(f"\n{int((~long_enough).sum())} petiolule stubs under {PETIOLULE_MM:.0f} mm dropped")
petiole = report("PETIOLES", pet_obj[long_enough], pet_plant[long_enough], pet_a[long_enough], pet_b[long_enough],
                 neighbourhood=1)

if a.json:
    json.dump(dict(workdir=work, min_traceable=a.min_traceable, leaflets=leaf, petioles=petiole), open(a.json, "w"), indent=1)
    print("\nwrote", a.json)
