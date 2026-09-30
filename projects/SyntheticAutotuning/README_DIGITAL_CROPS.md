# SyntheticAutotuning in Digital-Crops

The cowpea digital twin (Bailey lab, `SyntheticAutotuning`), kept here as the project's one final renderer
(image-to-l-system decision of 2026-09-28: every cowpea render comes from the twin's own Helios render).

## Provenance

- The first commit on this folder is a verbatim copy of image-to-l-system's read-only copy
  `inbox/SyntheticAutotuning` (copied 2026-09-21 from `/group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning`):
  sources, config, calibration, scripts, spectra, the twin fitting code, the syn2real code and the design documents.
  Its run history (builds, frames, synthetic sets, twin_work, logs, the Python env) and the third-party model
  weights were left out; the commit message lists them.
- Every later commit is an I/O addition or build configuration; the core algorithm (how a canopy is grown, lit,
  rendered and fitted) is unchanged. `scripts/diff_against_inbox.sh` prints the evidence: every non-code file is
  identical to upstream, and every upstream line of `main.cpp` that is not kept verbatim is listed (they are the
  lines moved into helper functions so a grown and an XML-loaded canopy share them).

## Additions (commits after the snapshot)

| addition | what it does |
| :--- | :--- |
| `CMakeLists.txt` | builds against `../../libs/Helios`; copies `assets/` (the high-resolution cowpea flower prototypes, absent from libs/Helios) into the build |
| `canopy.plant_xml <list>` | canopy read from plant-structure XML files instead of grown; `diag.write_plant_xml` writes grown plants |
| `diag.leafdump`, `diag.leafverts` (with UVs and textures), `diag.flowerdump` | organ dumps for organ-by-organ comparison |
| `--render-xml <xml or list> --camera <scene.json> --out <dir>` | renders refined plant XMLs through the unchanged render path, with the per-plant site map |
| `--render-obj <list> --camera <scene.json> --out <dir>`, `canopy.obj_list`, `output.write_depth` | renders plain meshes (baselines) in the twin scene, with a label map and depth |
| `paths.syn2real_dir`, `paths.soil_spec_xml` | where the Syn2Real_cowpea assets are (see below); defaults keep the upstream relative path |
| `canopy.species` (2026-09-29, block C) | which Helios library model the canopy is built from; see "Species" below |
| `output.write_class_ids` | per-pixel organ class map `<base>_class` in the render: 1 leaf, 2 open flower, 3 closed flower, 4 stem, 5 fruit (cowpea pod, sorghum panicle, tomato fruit) |
| `output.write_plant_obj <path>` | every plant as one OBJ with its leaf textures, after growth and yaw (for mesh-based scorers) |
| `leaf.optics`, `leaf.roll_min/max` | leaf optics choice (only `cowpea` exists); leaf roll range, applied only when given |

## Build

```bash
module load cuda/12.3.0            # farm; OptiX ray tracing needs CUDA
cd projects/SyntheticAutotuning
cmake -B build -DCMAKE_BUILD_TYPE=Release
make -C build -j 16 SyntheticAutotuning
```

The binary runs from `build/` (it reads `plugins/` there and `../config`, `../calib`, `../spectra`).

## Runtime assets: Syn2Real_cowpea

The render path loads `xml/soil_spec.xml` (soil spectra) and, when the rover body is drawn,
`T4_body_reflectance.xml` and `obj/T4rover_highres.obj` from a `Syn2Real_cowpea` folder, upstream at
`../../Syn2Real_cowpea` relative to the working directory. They are not part of this repository. Today they are read
from `/group/bnbaileygrp/bnbailey/Helios/projects/Syn2Real_cowpea` (image-to-l-system's `twin_render.py` links it into
its run tree). Use that copy: `image-to-l-system/scratch/Syn2Real_cowpea/xml/soil_spec.xml` differs from it and does not
reproduce the twin's renders. The proposed permanent home is
`image-to-l-system/dataset/twin_assets/Syn2Real_cowpea/`; point the binary at it with
`paths.syn2real_dir /abs/path/to/dataset/twin_assets/Syn2Real_cowpea` (or `paths.soil_spec_xml` for the soil file
alone). Until then the default relative path applies.

## Parity check

A grown render of the Plot201 twin (`twin_work/2023-06-20_Plot201-MAGIC262_rate2`, its layout and render overrides)
must reproduce the upstream binary's own `render_soil` output: identical site map (every plant IoU 1.000), RGB mean
absolute difference 0.66 of 255 or less. The binary runs from a directory laid out as
`<tree>/SyntheticAutotuning/build` (with `plugins/`), `<tree>/SyntheticAutotuning/{calib,config}` and
`<tree>/Syn2Real_cowpea`; image-to-l-system's `twin_render.ensure_runtree()` builds it, and `TWIN_RENDER_BIN` /
`TWIN_RENDER_RUNTREE` point that wrapper at this build. The procedure and scripts are image-to-l-system
`scratch/20260928_twin_render/parity_run.py` (steps A, B, Bp) and `parity_compare.py`.

## Species (block C, 2026-09-29)

`canopy.species` (default `cowpea`) names the Helios plant-library model (`loadPlantModelFromLibrary`), and a table in
`main.cpp` maps it to the shoot type the shoot-parameter overrides are written to: cowpea `trifoliate`, sorghum and
tomato `mainstem`. Heesup approved this change to the plant-model configuration on 2026-09-29; the fitting algorithm
(`twin/fit.py`, the site/age/seed/yaw search, `twin/canopy.py`) is unchanged.

- **Cowpea is unchanged.** With the key absent every cowpea code path runs as before: the label maps of `--render-xml`,
  `--render-obj`, a grown render and the label rasterizer were byte-identical to the previous binary (image-to-l-system
  `scratch/20260929_twin_sorghum/jobs/build_parity.sbatch`); the grown render's RGB differs only by GPU ray-tracing
  noise (mean 0.13 of 255).
- **Other species keep the library's organs.** The cowpea-only settings (0.002 m petiole radius, the scanned leaflet OBJ,
  the leaflet size default, the flower block with `CowpeaFlowerPrototype_custom`, the cowpea phenology thresholds) apply
  to cowpea alone. A sorghum or tomato plant keeps its library prototypes (sorghum strap leaf and panicle; tomato
  compound leaf, flower and fruit) and the phenology its `build<Species>Plant` sets; a flat shoot key
  (`canopy.internode_length_max`, `canopy.phyllochron`, `canopy.max_nodes`, bud break, `leaf.prototype_scale_*`,
  `flower.*`, `fruit.prototype_scale`, `phenology.*`) applies only when the config gives it. `leaf.use_obj_mesh 1` and
  `leaf.angle_tracking` without explicit Beta parameters are errors for a non-cowpea species.
- **Output names** carry the species (`cowpea_040_...`, `sorghum_040_...`).
- **Configs.** `config/baseline.cfg` is cowpea. `config/sorghum.cfg` is the T4 rover variant (real sorghum plots:
  Basler camera, lamp rig, rover, 0.73 m rows); its closing comment block lists the overrides of the synthetic-scene
  variant (the multi-crop benchmark's 720 px nadir camera, sun, no rover). Its plant is the Digital-Crops generator's
  sorghum config at its means with the "tall" internode (0.28 m), the plant the benchmark's library start uses.
- **Leaf optics are cowpea's for every species** (`leaf.optics cowpea`, the config's PROSPECT parameters). Per-species
  optics are a decision for Heesup; silhouettes and label maps do not depend on it.
- **Python side.** `twin/species.py` holds the per-species priors the fit is given: age window, row and in-row spacing,
  leaflets per leaf (cowpea 3, sorghum 1, tomato 7), the leaflet filters of `leaflets.py`, the vegetation mask (a* for
  cowpea, ExG for sorghum and tomato) and the config file. `raster.run` picks the species' config from
  `canopy.species`; `fit.fit_sparse` accepts a camera, a plant list and the in-row separation for frames that are not
  T4 rover frames (for example one-plant synthetic scenes).

- **Tomato (block C step 2, 2026-09-29).** `config/tomato.cfg` restates the library tomato (internode 0.04 m, 16 nodes,
  phyllochron 2 d, bud break 0.25, a 0.18 m truss of 6 flowers bending -900 deg/m, flower scale 0.05, fruit 0.15,
  phenology 40/5/5/30) with the benchmark library start's means; its active camera is the synthetic benchmark's 720 px
  nadir view (sun, no rover), and the TomatoWUR variant is the closing override block. `flower.peduncle_pitch` and
  `flower.peduncle_curvature` apply to non-cowpea species when given. The species table carries tomato's age window
  (DAP 10-90), 1.5 m beds with single or paired rows (`row_pattern`) and 0.45 m in-row spacing, and 7 leaflets per leaf.
- **Posed camera (`camera.pose`).** The label rasterizer takes a full camera pose: 12 comma-separated numbers, the eye
  and the image-right, image-up and backward axes, in the twin frame. Absent, the nadir camera is used and every map is
  unchanged. `twin/real.py` builds it for TomatoWUR (`wur_camera`, `wur_view`, `pose_overrides`, `no_rover_mask`);
  `fit.fit_sparse` places a plant that carries `ground_xy` at that known base; `soil.soil_overrides(soil_map=False)`
  leaves the library soil for frames without a soil map.
