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
