"""Write the calibrated Helios model from a fit: the flat config the harness reads, so
`SyntheticAutotuning render|raster ../config/<file>.cfg` with `canopy.layout_file` reproduces
the fitted scene, and a companion JSON with the values grouped the way a PlantArchitecture
library entry would take them.
usage: twin_export_model.py <fit workdir> [--opt stage1_opt.json] [--out name]
"""
import argparse, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import twin.fit as F, twin.raster as TR

ap = argparse.ArgumentParser()
ap.add_argument("work"); ap.add_argument("--opt", default=None); ap.add_argument("--out", default=None)
a = ap.parse_args()
work = os.path.abspath(a.work)
fit = json.load(open(os.path.join(work, "fit.json")))
ov = dict(F.BASE); ov.update(fit["overrides"])
if a.opt:
    ov.update(json.load(open(a.opt)).get("best_overrides", {}))
name = a.out or os.path.basename(work)
# A complete, standalone config: every key of the baseline (the harness has no include), with the
# calibrated values written over it, so `SyntheticAutotuning raster|render ../config/twin_<name>.cfg`
# reproduces the fitted scene without further overrides.
base = {}
for line in open(os.path.join(TR.PROJECT, "config", "baseline.cfg")):
    line = line.split("#", 1)[0].split()
    if len(line) >= 2:
        base[line[0]] = line[1]
base.update({k: v for k, v in ov.items() if not k.startswith("raster.")})
base["canopy.layout_file"] = os.path.join(work, "layout.txt")
cfg_path = os.path.join(TR.PROJECT, "config", f"twin_{name}.cfg")
with open(cfg_path, "w") as f:
    f.write(f"# Calibrated twin of {fit['target']}\n# written {time.strftime('%Y-%m-%d %H:%M')} by scripts/twin_export_model.py over config/baseline.cfg\n")
    for k, v in sorted(base.items()):
        f.write(f"{k:34s} {v}\n")
model = {
    "source_frame": fit["target"],
    "camera": {"hfov_deg": ov.get("camera.hfov"), "height_m": ov.get("camera.height")},
    "shoot_parameters.trifoliate": {
        "phytomer.leaf.prototype_scale": [ov.get("leaf.prototype_scale_min"), ov.get("leaf.prototype_scale_max")],
        "phytomer.petiole.length": [ov.get("leaf.petiole_length_min"), ov.get("leaf.petiole_length_max")],
        "phytomer.petiole.pitch_deg": [ov.get("leaf.petiole_pitch_min"), ov.get("leaf.petiole_pitch_max")],
        "phytomer.leaf.pitch_normal_deg": [ov.get("leaf.pitch_mean", 0.0), ov.get("leaf.pitch_std")],
        "internode_length_max": ov.get("canopy.internode_length_max"),
        "phyllochron_min": ov.get("canopy.phyllochron"),
    },
    "leaf_angle_distribution.beta": [ov.get("leaf.angle_beta_mu"), ov.get("leaf.angle_beta_nu")],
    "phenology": {k.split(".")[1]: ov.get(k) for k in ov if k.startswith("phenology.")},
    "scene": {"layout": os.path.join(work, "layout.txt"), "plants": len(fit["sites"]),
              "ages_days": [s["age"] for s in fit["sites"]], "per_plant_iou": [s.get("iou") for s in fit["sites"]]},
    "not_calibrated": ["leaf optics (previous project's PROSPECT fit)", "soil", "lighting", "phenology thresholds (previous project)"],
}
json_path = os.path.join(work, "calibrated_model.json")
json.dump(model, open(json_path, "w"), indent=1)
print("wrote", cfg_path, "and", json_path)
