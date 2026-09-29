# Hand-off: Vulkan compute backend returns NaN for all camera pixels with plant geometry

## Task

In the Helios repo at `/group/bnbaileygrp/bnbailey/Helios`, the radiation plug-in's **Vulkan
compute (software BVH) backend** produces `NaN` for every camera pixel as soon as
plantarchitecture geometry is in the scene. It fails **silently** — no error, no warning, just
a fully black JPEG. The same scene on the CUDA/OptiX 8 backend renders correctly.

Find and fix the root cause. Also make the failure non-silent, so this can never again present
as "my scene is too dark".

## Environment

- Cluster: UC Davis FARM. Login nodes have **no CUDA**, so `cmake` silently selects the Vulkan
  fallback there. GPU nodes (`--partition=gpu-6000_ada-h`, `--gres=gpu:1`) have CUDA 12.6 and
  the bundled OptiX 8.1 SDK.
- Build environment is pinned in
  `projects/SyntheticAutotuning/scripts/env.sh` (`source` it before cmake/make — the cmake and
  gcc module PATH entries point at an unpopulated spack view, so concrete prefixes are used).
- **You do not need a CUDA-less machine to reproduce.** The radiation CMakeLists exposes
  `-DFORCE_VULKAN_BACKEND=ON`, which forces the Vulkan path even when CUDA is present. Use
  that on a GPU node so you can A/B against OptiX on identical hardware and identical scenes.

## Reproduction

A working reproducer already exists:

```bash
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh
cmake -S . -B build-vk -DCMAKE_BUILD_TYPE=Release -DFORCE_VULKAN_BACKEND=ON
make -C build-vk -j8
cd build-vk
./SyntheticAutotuning render ../config/baseline.cfg 7 \
    camera.resolution_x 200 camera.resolution_y 160 camera.samples 8 \
    canopy.age 30 post.ccm_file "" output.folder ../frames_vk/
```

`main.cpp` prints a diagnostic line after `runBand`:

```
DIAG camera red: n=<pixels> nan=<count> min=<..> max=<..>
```

- Vulkan backend: `nan=32000` out of 32000 (100 %).
- OptiX 8 backend (same command, `-DFORCE_VULKAN_BACKEND=OFF`, on a GPU node):
  `nan=0 min=2.11e-07 max=0.4558`.

Consider also building a **minimal standalone reproducer** — one radiation camera, one
rectangle light, one `PlantArchitecture` cowpea plant, `setScatteringDepth 2` — so the bug is
isolated from this project's configuration. That will make the fix easier to test and easier to
upstream.

## What has already been bisected

Ruled **out** — NaN persists with each of these disabled:

| hypothesis | test | result |
|---|---|---|
| PROSPECT / leafoptics spectra | `leaf.use_prospect 0` (flat green spectrum instead) | still NaN |
| Any custom spectra at all | `plant.assign_spectra 0` (no reflectivity/transmissivity set on any plant primitive) | still NaN |
| Periodic boundary | `light.periodic_boundary 0` | still NaN |
| Colour-correction matrix | `post.ccm_file ""` | still NaN |

Ruled **in**:

| observation | evidence |
|---|---|
| It needs **plant geometry** | Ground tile only (`canopy.germination_fraction 0.0001`, no plants): `nan=0 min=0.000229 max=71.6`. Add plants: 100 % NaN. |
| It is in the **scattering pass** | `light.scattering_depth 0` → `nan=0` (all zeros). Depths 1, 2 and 3 → 100 % NaN. Note depth 0 is not a clean control: the camera ray trace runs inside the scattering phase, so zeros there are expected. |
| It is **backend-specific** | Identical scene, identical seed: OptiX 8 clean, Vulkan all-NaN. |
| It is **not** a scale/geometry-count threshold alone | Fails at 0.26 M primitives and at 1.6 M alike. |

So: **Vulkan backend + plantarchitecture geometry + scattering enabled → NaN**, independent of
radiative properties.

## Where to look

Backend sources: `plugins/radiation/src/backends/`
- `VulkanComputeBackend.cpp` / `.h` — dispatch, buffer setup, result readback
- `VulkanDevice.cpp` / `.h`
- `BVHBuilder.cpp` / `.h` — the software BVH, only used by this backend

Shaders: `plugins/radiation/shaders/`
- `diffuse_raygen.comp` — the scattering pass, the prime suspect given the bisection
- `camera_raygen.comp` — camera trace
- `common/texture_mask.glsl` — **strong suspect**: plantarchitecture leaves are textured
  triangles with alpha masks (e.g. `CowpeaLeaf_tip_centered.png`), whereas the ground tile that
  renders fine is untextured. This is the most conspicuous difference between the working and
  failing scenes.
- `common/intersections.glsl` — plant meshes contain very small and possibly degenerate
  triangles; a division by a near-zero determinant or edge length would produce NaN that then
  propagates through the whole scatter buffer.
- `common/bvh_traversal.glsl`, `common/buffer_indexing.glsl`, `common/random.glsl`

Suggested first probes, in order of expected yield:
1. Render a scene with plant geometry but **textures stripped** (replace leaf prototypes with
   untextured patches, or clear the texture file on the leaf prototype). If that renders clean,
   it is the alpha-mask path.
2. Scan the plant geometry for degenerate primitives (zero area, NaN/inf vertices, zero-length
   normals) before the trace and count them. `Context::getPrimitiveVertices` /
   `getPrimitiveArea` over `plantarchitecture.getAllUUIDs()`.
3. Instrument the scatter buffers (`TBS_top` / `TBS_bottom` in `RadiationModel::runBand`) and
   the backend's `RayTracingResults::radiation_in` for the first non-finite value, to establish
   whether NaN originates in the direct pass, the scatter pass, or only the camera pass.
4. Bisect by scene: one leaf; one plant; one plant with leaves removed
   (`PlantArchitecture::removeShootLeaves`).

## Definition of done

1. **Root cause identified and fixed** — the reproducer above renders with `nan=0` on the
   Vulkan backend, and its output is quantitatively comparable to the OptiX 8 render of the same
   scene and seed (same camera geometry, same lighting; compare per-band mean/median and the
   foliage colour ratios, not pixel-exact equality — the two backends sample differently).
2. **No silent failure.** Even if some corner case survives, the backend must detect non-finite
   camera or scatter output and raise a `helios_runtime_error` (or at minimum an unmissable
   warning naming the backend). A black image with no diagnostic is the part of this bug that
   cost the most time.
3. **A regression test** in `plugins/radiation/tests/selfTest.cpp` that builds a small scene
   containing textured plant geometry, runs a camera band with scattering enabled, and asserts
   all camera pixel data is finite. It must run under the Vulkan backend
   (`-DFORCE_VULKAN_BACKEND=ON`) in CI, not only under OptiX — the existing tests evidently
   pass on OptiX while this bug is live.
4. If the true fix is large, an acceptable interim outcome is: a precise root-cause writeup, the
   guard from (2), and a clear startup warning when the Vulkan fallback is selected, so users
   know they are on an unvalidated path.

## Cautions

- **Do not "fix" this by disabling the Vulkan backend or forcing an OptiX requirement.** The
  fallback exists so Helios runs without CUDA; that capability should keep working. Removing it
  would be a scope change, not a fix — flag it and ask rather than doing it unilaterally.
- Do not change the OptiX backends' numerics to match Vulkan. OptiX is the reference here; it
  is the one producing correct output.
- Be careful with `git` state in this repo: the working tree has uncommitted asset files
  (`plugins/plantarchitecture/assets/...`). Check `git status` before any checkout/reset/clean,
  and do not discard them.
- Build artefacts: this project already has `build/` (Vulkan, from a login node) and
  `build-gpu/` (CUDA/OptiX). Use a separate `build-vk/` for your work so you do not clobber
  either.

## Background, if useful

This surfaced during a synthetic-vs-real domain-gap study
(`projects/SyntheticAutotuning/PHASE1_FINDINGS.md`). It cost roughly an afternoon: the black
images were initially read as an exposure or white-balance problem, because the pipeline was
being changed at the same time and a silent all-NaN buffer is indistinguishable from a
badly-exposed scene. The scene-level and radiative-property hypotheses were all eliminated
before the backend was suspected at all.
