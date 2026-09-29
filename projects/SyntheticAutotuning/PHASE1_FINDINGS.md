# Phase 1 — Syn2Real gap diagnostic (cowpea flower detection)

Run: `./env/bin/python -m syn2real.report` (27 s) and `-m syn2real.tier1` (3 min, GPU).
Inputs: 263 real tiles / 1,991 boxes vs. 1,307 synthetic tiles / 10,240 valid boxes, all 640×640.

## Headline

**The synthetic and real sets are completely disjoint in feature space.**

| Tier-1 metric | value | reading |
|---|---:|---|
| KID (DINOv2), real vs real | −0.09 ± 0.005 | noise floor |
| KID (DINOv2), real vs synthetic | **+29.21 ± 0.07** | ~300× the floor |
| CCDM (object crops), real vs real | −0.017 ± 0.009 | noise floor |
| CCDM (object crops), real vs synthetic | **+10.06 ± 0.05** | |
| PRDC coverage (scene) | **0.000** | no real scene has a synthetic neighbour |
| PRDC precision / recall / density | 0.000 / 0.000 / 0.000 | manifolds do not intersect at all |
| Domain-classifier AUC (scene) | **1.0000** | a *linear* probe separates them perfectly |
| Domain-classifier AUC (object crops) | **1.0000** | |

These are the numbers every later phase has to move. Coverage 0.000 and AUC 1.0000 are the
regression baseline.

## The sensor chain is not the lever

Post-hoc corrections applied to the synthetic images, cumulative:

| chain | domain AUC | KID | coverage |
|---|---:|---:|---:|
| baseline | 1.0000 | 29.15 | 0.000 |
| + JPEG re-encode at real quant table (quality **75**, quant sum 1858 — exact match) | 1.0000 | 27.51 | 0.000 |
| + unsharp (edge sharpness) | 1.0000 | 27.31 | 0.000 |
| + matched sensor noise (σ 1.51 added) | 1.0000 | 27.19 | 0.000 |
| + global Lab colour transfer to real moments | 1.0000 | 28.14 | 0.000 |

Sensor-level fixes buy ~7 % of KID and nothing at all in AUC or coverage. Global colour
matching in post makes it *worse*. **The gap is dominated by scene content, geometry and
material appearance.** The sensor fixes are still worth applying (they are nearly free, and
compression/noise are exactly the shortcut features a detector will latch onto), but they must
not be mistaken for progress on the real problem.

## Class definition — resolved

Both sides label the same thing: **buds + open flowers + senescent flowers** (`audit/crops_real.png`,
`audit/crops_synthetic.png`). No relabeling is needed. An earlier hypothesis that the real set
labelled only open corollas was wrong — the real crops are dominated by cream/yellow buds.

Weed flowers are correctly excluded on both sides.

## Ranked Tier-0 gaps

Full table in `audit/gap_report.md` / `.csv`; distributions in `audit/gap_distributions.png`.
Verdicts are asymmetric: being *wider* than real is not penalized, being *shifted* or *too narrow* is.

### SHIFTED — synthetic is centred in the wrong place (fix these)

| statistic | real | syn | W1/IQR | controlled by |
|---|---:|---:|---:|---|
| `veg_hue_deg` | 84° | 100° | 3.74 | leaf reflectance spectra |
| `edge_sharpness` | 2.55 | 1.92 | 1.94 | **synthetic is BLURRIER than real** — `lens_diameter`, `camera_samples`, downscale |
| `lab_b_mean` | 30.3 | 17.9 | 1.83 | leaf spectra + white balance |
| `sat_mean` | 0.552 | 0.372 | 1.70 | saturation / exposure |
| `veg_sat` | 0.545 | 0.388 | 1.48 | leaf reflectance spectra |
| `hf_energy_frac` | 0.0039 | 0.0019 | 1.08 | optical MTF + noise |
| `noise_sigma` | 2.27 | 1.78 | 1.07 | shot/read noise |
| `img_nn_dist_px` | 83.3 | 36.7 | 0.74 | **synthetic flowers are 2× more clustered** |
| `local_rms_contrast` | 8.05 | 6.90 | 0.69 | light geometry |
| `lab_a_mean` | −18.7 | −15.1 | 0.66 | leaf spectra + white balance |
| `soil_hue_deg` | 40° | 54° | 0.65 | soil reflectivity |
| `L_p05_shadow` | 20.8 | 15.7 | 0.64 | light geometry + scattering depth |
| `psd_slope` | −2.98 | −3.10 | 0.61 | optical MTF + noise |
| `obj_abs_log_aspect` | 0.304 | 0.762 | 0.58 | flower/peduncle orientation |
| `obj_minor_px` | 28.0 | 17.5 | 0.58 | flower scale |
| `obj_size_px` | 33.0 | 26.1 | 0.55 | GSD + flower scale |
| `obj_width_px` | 35.0 | 19.0 | 0.51 | inflorescence geometry |

The colour block is one coherent failure: synthetic foliage is **hue-shifted toward cyan-green
(100° vs 84°), desaturated (0.39 vs 0.55) and yellow-deficient (b* 17.9 vs 30.3)**. That is the
single largest interpretable signal in the report.

### TOO-NARROW — synthetic fails to reach real modes

`shadow_frac` (0.0048 vs 0.0008, cov deficit 0.90) — synthetic canopies lack deep inter-leaf
shadow; `veg_value`, `veg_L` (exposure); `soil_sat`; `img_obj_area_frac`.

### Notable smaller findings

- **`img_edge_trunc_frac`: real 0.000, synthetic 0.118.** ~12 % of synthetic boxes touch the tile
  border; essentially no real box does. The real annotation pipeline drops edge-truncated boxes.
  A convention mismatch that teaches the detector to fire on partial objects.
- **Object orientation.** Real `obj_log_aspect` is symmetric about zero (median +0.041, skew −0.11,
  p5/p95 −0.70/+0.71) — objects randomly oriented in the image plane, exactly as a nadir view of
  randomly-azimuthed buds should look. Synthetic is strongly skewed vertical (median −0.615,
  skew +1.22, 68.8 % taller-than-wide). Synthetic buds stand erect and aligned; real ones point
  every direction. Suspects: `inflorescence.pitch` forced to 90 in `Syn2Real_cowpea/main.cpp:115`
  (library default is 40–60), `peduncle.roll = 90`, and `base_yaw` restricted to ±20°.
- **Canopy closure is NOT a major gap** (real median 0.975, syn 0.933; cov deficit 0.02). My initial
  visual impression from a handful of tiles was wrong — measured over the full sets the
  distributions largely overlap, with synthetic carrying a heavier open-canopy tail (min 0.52 vs
  0.65). Under the asymmetric objective that extra spread is acceptable.
- 10 synthetic boxes (0.10 %) are degenerate (zero width or height); 90 more are sub-2px.
- Framing is fine: `obj_center_x/y` W1/IQR ≈ 0.02.

## Blocker for Phase 2

The source full-resolution renders for *this particular* tiled set (frame indices 050/060) are not
on the filesystem — other runs of the same pipeline are (2048×2048, with per-class
`bbox_openflowers` / `bbox_closedflowers` / `bbox_pods` files), but none reproduce the tiled set's
box-aspect distribution, so the tiling recipe cannot be reverse-engineered reliably.

Phase 2 needs, for the **real** capture chain: raw un-tiled frames, camera/lens model, working
distance, and the crop/resize recipe that produced the 6 × 640×640 tiles. Location unknown.

---

# Root cause of the colour gap: the leaf reflectance library

The largest Tier-0 signal was foliage colour. Rather than search for it with render sweeps,
it can be evaluated in closed form: measured leaf spectra × light spectrum × camera spectral
response, white-balanced against a perfect diffuser (the renderer's own convention).
`syn2real/spectra.py` does this; no GPU needed.

## Empirical target, measured from the images

Median RGB of ExG-classified foliage pixels:

| set | R | G | B | G/R | **G/B** | hue | sat |
|---|---:|---:|---:|---:|---:|---:|---:|
| real | 96.9 | 120.6 | 56.7 | 1.24 | **2.13** | 82° | 0.533 |
| synthetic | 85.1 | 107.9 | 69.2 | 1.27 | **1.56** | 94° | 0.357 |

**The green/red ratio already matches (1.24 vs 1.27). The entire gap is excess BLUE** —
synthetic foliage carries 22 % more blue than real. Excess blue lifts the minimum channel,
which is what produces both the cyan hue shift and the desaturation (HSV saturation is
(max−min)/max). This is a more specific diagnosis than "synthetic looks washed out".

## The measured spectra carry a stray-light offset

`projects/Syn2Real_cowpea/xml/LICOR_all_spec.xml`, 190 reflectance spectra, median values:

| λ (nm) | 450 | 550 | 650 | 680 | 800 | G/R (550/650) |
|---|---:|---:|---:|---:|---:|---:|
| measured **R** | 0.081 | 0.164 | 0.091 | **0.083** | 0.536 | **1.81** |
| measured **T** | 0.020 | 0.099 | 0.024 | **0.011** | 0.431 | |
| canonical healthy dicot | 0.040 | 0.150 | 0.035 | 0.030 | 0.500 | 4.29 |

Three independent lines of evidence that the reflectance channel carries a wavelength-flat
additive offset of ≈0.05:

1. **R(680) = 0.083 but T(680) = 0.011.** At the chlorophyll absorption maximum a leaf both
   reflects and transmits almost nothing. A leaf cannot reflect 8× what it transmits there.
   The transmittance spectra are clean; only reflectance is affected — consistent with
   specular/stray-light leakage in the reflectance measurement geometry.
2. **One constant fixes three widely separated bands at once.** Subtracting 0.053 puts blue
   (0.081→0.028), red (0.091→0.036) and the NIR plateau (0.536→0.481) simultaneously onto
   canonical values. No biological variation does that.
3. **G/R = 1.81 is not a green leaf.** Healthy dicots are ~4.3. A leaf with G/R 1.8 renders
   grey-green, which is exactly what the synthetic images show.

## Correction and its limits

`syn2real/spectra_fix.py` writes an offset-corrected copy (`spectra/LICOR_all_spec_corrected.xml`);
per-spectrum offset is anchored on R(680) → 0.030. Median offset 0.053 (p5 0.042, p95 0.085).

| | R450 | R550 | R650 | R800 | G/R | predicted hue | predicted sat | predicted G/B |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| original | 0.081 | 0.164 | 0.091 | 0.536 | 1.81 | 94° | 0.137 | 1.16 |
| corrected | 0.028 | 0.106 | 0.036 | 0.481 | 2.96 | 90° | 0.263 | 1.35 |
| canonical | 0.040 | 0.150 | 0.035 | 0.500 | 4.29 | — | — | — |
| **real image target** | | | | | | **82°** | **0.533** | **2.13** |

The correction moves everything the right way but **does not fully close the gap**: a flat
subtraction also takes 0.053 off the green peak, leaving R550 at 0.106 against a canonical
0.150, so G/R reaches 2.96 rather than 4.29. The offset is the right *shape* but not a
complete model of the artifact.

**Recommendation: generate leaf spectra with the `leafoptics` PROSPECT/Fluspect plugin instead
of the measured library.** `Syn2Real_cowpea/main.cpp` already includes `LeafOptics.h` but never
uses it. That gives physically self-consistent spectra by construction plus a handful of
interpretable knobs (`chlorophyllcontent`, `carotenoidcontent`, `anthocyancontent`,
`numberlayers`, `watermass`, `drymass`) that are exactly the right parameters for the Phase 4/5
optimizer to own. The offset-corrected library stays available as a drop-in if you would
rather keep measured spectra.

Caveat: these are closed-form predictions from the spectral inputs alone. They exclude
multiple scattering, soil bounce, specularity and the renderer's image-correction pipeline,
so they identify the *direction and root cause* but the magnitudes need a render to confirm.

## Build

`build/SyntheticAutotuning` compiles (Vulkan backend; CUDA/OptiX not present on this node).
`scripts/env.sh` pins the toolchain — the cmake/gcc module PATH entries point at an unpopulated
spack view, so the concrete spack prefixes are used directly.

---

# Camera geometry (resolved) and the PROSPECT result

## Real camera chain — pinned

Basler acA2500-20gc: PYTHON 5000, **2590 × 2048**, 4.8 µm pixels, **12.44 × 9.83 mm** sensor.
With a 12 mm lens this gives HFOV = 2·atan(12.44/24) = **54.8°** and VFOV = 2·atan(9.83/24) =
**44.5°**, matching the stated values exactly.

| quantity | value |
|---|---|
| working distance to canopy | 1.10 m |
| camera height | 1.64 m |
| implied canopy top | **0.54 m** |
| field of view at canopy | 1140 × 901 mm |
| **native GSD** | **0.440 mm/px** (both axes) |

## The object-size gap is camera geometry, not flower size

Three independent measurements agree:

| measurement | ratio real/syn |
|---|---:|
| ExG canopy texture scale (cover- and blur-controlled) | 1.21 |
| annotated object size | 1.27 |
| GSD predicted from camera geometry, synthetic canopy top 0.2 m | 1.25 |

Synthetic GSD is 0.55–0.63 mm/px because the camera sits at z = 1.58 m over a canopy only
~0.2 m tall (working distance ≈1.38 m). **Fix: camera height 1.58 → 1.64 m and grow the canopy
to ~0.54 m.** That one change closes the object-size gap, reduces soil visibility and deepens
inter-leaf shadow — three ranked gaps at once.

Correction to an earlier reading in this document: an uncontrolled autocorrelation measurement
suggested synthetic leaves were ~2× too large. That was an artifact of the soil-patch confound
(synthetic has 3× more soil, and ExG autocorrelation is dominated by vegetation/soil patch
structure). Restricting both sets to closed-canopy tiles and matching sharpness collapses the
ratio to ~1.0.

## PROSPECT does NOT close the colour gap

`main.cpp prospect-grid` dumps leaf spectra from the *renderer's own* LeafOptics/PROSPECT
implementation (3000 Latin-ish samples over Cab 10–80, Car 2–25, Cant 0–10, N 1.0–2.5).
Convolving with the CREE 6500K source and the Basler response gives the achievable envelope:

| | min | median | max | **real target** |
|---|---:|---:|---:|---:|
| G/B | 1.00 | 1.24 | **1.54** | **2.13** |
| G/R | 0.79 | 1.07 | 1.35 | 1.24 |
| hue | 24° | 84° | 180° | 82° |

**Hue is reachable; the G/B separation is not.** The current synthetic images already sit at
G/B ≈ 1.56–1.64, i.e. at or slightly above the top of the entire PROSPECT envelope. No pigment
combination gets to 2.13, so **switching to PROSPECT will not fix the colour gap.** Neither does
the illuminant: the other light source in the Helios library (ActiveGrow RedBloom) gives G/B 1.46.

Pigment sensitivity, for the Phase 4/5 optimizer (Spearman over the grid):

| param | ρ(hue) | ρ(sat) |
|---|---:|---:|
| Cab | **+0.865** | −0.731 |
| N | −0.232 | +0.479 |
| Cant | −0.241 | −0.334 |
| Car | −0.221 | +0.026 |
| Cw, Cdm | ~0 | ~0 |

Chlorophyll dominates hue; leaf structure parameter N is the main saturation lever. Water and
dry mass have no visible-band leverage and should be fixed, not optimized.

**Still switch to PROSPECT** — the measured library is objectively artifact-contaminated and
PROSPECT gives physically self-consistent spectra with interpretable knobs. Just do not expect
it to close the colour gap.

## Where the colour residual actually lives

The gap is downstream of the leaf model, in the camera colour transform. A colour camera's raw
Bayer response is inherently desaturated because the filter passbands overlap; every ISP applies
a colour-correction matrix to restore separation. Helios' pipeline white-balances but applies no
such matrix by default, which is consistent with synthetic foliage being stuck near the physical
G/B limit while the real JPEGs sit well above it.

*Not established:* I fitted a 3×3 matrix mapping synthetic to real across foliage/soil/flower and
got zero residual — but three materials against a 3×3 is an exactly-determined system, so that
result is arithmetic, not evidence. It is reported here only so it is not mistaken for a finding.

Helios already has the right machinery: `CameraCalibration`, `RadiationModel::calibrateCamera()`,
and `applyCameraColorCorrectionMatrix(ccm_file)`; colour-board spectra for Calibrite ColorChecker,
DGK DKK and Datacolor SpyderCHECKR ship in `plugins/radiation/spectral_data/color_board/`, and
`Syn2Real_cowpea/MineralColorboard.xml` suggests a board was used at some point.
**The clean fix is a real frame containing a colour board.** Failing that, the CCM has to be fitted
from many matched colour clusters across the two datasets, which is confounded by the materials
genuinely differing.

---

# Camera colour calibration from the SpyderCHECKR board

## Result

The colour gap is closed. Fitting PROSPECT pigments through the **full** pipeline
(white balance → colour-correction matrix → tone curve) reproduces the real foliage colour
essentially exactly, and — the real check — yields *physically sensible* pigment values.

| pipeline | achievable G/B | best match to real | chroma error | fitted Cab |
|---|---|---|---:|---:|
| without CCM (current renderer) | 1.00 – 1.59 | G/R 1.01, G/B 1.54 | 0.0937 | 16 µg/cm² (implausible) |
| **with CCM (calibrated)** | 1.03 – ∞ | **G/R 1.23, G/B 2.41** | **0.0022** | **47 µg/cm² (healthy leaf)** |
| real 2023-07-28 target | | G/R 1.23, G/B 2.43 | | |

A 43× reduction in chroma error. The internal check matters as much as the number: fitting
through the wrong pipeline forced chlorophyll down to 16 µg/cm² to fake the missing chroma,
which is not a healthy field leaf. Fitting through the correct pipeline lands on 47 µg/cm²,
right where a field-grown legume should be.

**Recommended cowpea leaf parameters** (centroid of the 50 best-matching samples), for
`LeafOpticsProperties`:

```
chlorophyllcontent = 47.5     carotenoidcontent = 14.6
anthocyancontent   = 6.5      numberlayers      = 1.92
watermass          = 0.0149   drymass           = 0.0076
```

## The matrix

`calib/ccm_camA_20230728.xml`, ready for `applyCameraColorCorrectionMatrix("camA", ...)`:

```
1.327907  -0.556237   0.145156
-0.210308  1.575028  -0.412002
0.201699  -1.419851   2.144966
```

Classic ISP structure: strong positive diagonal with negative off-diagonals that subtract
cross-channel contamination. This is the stage Helios does not model — a colour camera's raw
Bayer response is inherently desaturated because the filter passbands overlap, and every ISP
applies such a matrix to restore separation. Its absence is exactly why synthetic foliage sat
pinned at the physical G/B limit while real JPEGs sat well above it.

Fit quality: 18/24 patches usable (6 clipped at ≥250 DN), fitted tone-curve gamma 2.00,
residual **19.68 DN RMS vs 33.48 for per-channel gain alone — 1.70× better**, which is what
justifies using a matrix rather than a white-balance tweak.

## What the boards could NOT establish

**Illuminant is undetermined.** Candidates rank CREE 6500K 19.68, solar diffuse 20.46, solar
direct 21.09, solar global 21.11, ActiveGrow RedBloom 24.33. The top four are within 7 % of each
other — a 3×3 matrix absorbs most of the difference between a 6500 K white LED and daylight, so
the board cannot discriminate. Only RedBloom is clearly excluded. The lighting question behind
the `shadow_frac` and `L_p05_shadow` gaps stays open.

**Drift is unmeasured.** Of the three boards only the 2023-07-28 frame extracted reliably
(orientation correlation 0.875). The 2023-08-28 frame — the one that would have given a
same-board, same-camera, one-month drift estimate — failed extraction (correlation 0.264 after
sweeping detection threshold, inset and all eight dihedral arrangements); it sits at a steep
tilt and small scale in frame. The 2022-10-26 DGK frame reached only 0.706 and is a different
board, site and season in any case. **No drift number should be quoted from this work.**

Consequence: the CCM is validated for the **2023-07-28 session (118 of 263 real images)** and is
an assumption everywhere else. The 2023-07-25 session differs by up to 21.5 DN with non-uniform
per-channel ratios (R 0.873, G 0.836, B 0.776), but that confounds camera drift with genuine
scene difference and cannot be separated with the data available.

## Board extraction, for reuse

`syn2real/board_extract.py` finds a board in a full frame with no manual input:
1. **Locate** by chroma variance only — deliberately blind to a black/white checkerboard
   calibration target, which has huge luminance variance but no chroma and would otherwise win
   (the 2022-10 frame contains one).
2. **Measure extent** with luminance *and* chroma variance in a tight window — chroma alone
   clips off the neutral patch column and returns a 6×3 rectangle instead of 6×4.
3. **Resolve orientation** by trying all eight dihedral arrangements and keeping the one whose
   sampled chromaticity best correlates with the reference. This doubles as the correctness
   check: 0.875 is a good extraction, 0.264 is a failed one.

Tone-curve gamma is fitted jointly with the matrix rather than assumed to be sRGB, since a
camera JPEG applies its own curve and the mismatch would otherwise bias the matrix.

---

# Renderer: colour pipeline resolved

## The white balance was applied twice

Helios applies a scene-independent white balance derived from the camera spectral
response. Leaving `CameraProperties.white_balance` at its default `"auto"` applies it a
**second** time, squaring the per-channel gains. Green has the largest raw response so its
gain is smallest; squaring suppresses green hardest relative to red and blue. The signature
is unmistakable — tan soil renders **pink** and green foliage renders **grey**.

Verified directly on identical scenes:

| `camera.white_balance` | background RGB | ordering | verdict |
|---|---|---|---|
| `auto` | 240, 213, 222 | R>B>G | pink — wrong |
| **`off`** | **223, 213, 203** | **R>G>B** | **tan — matches the soil reflectance (0.50/0.44/0.37)** |

`config/baseline.cfg` now sets `camera.white_balance off`.

## Colour match, end to end in the renderer

With the white balance corrected, the CCM finally receives the input it was fitted for:

| | G/R | G/B | hue | sat |
|---|---:|---:|---:|---:|
| render, no CCM | 1.05 | 1.23 | 76° | 0.184 |
| **render + CCM** | **1.23** | **2.42** | **80°** | **0.588** |
| **real 2023-07-28** | **1.23** | **2.43** | **78°** | **0.588** |

G/R exact, G/B within 0.4 %, saturation exact, hue within 2°. This is measured on rendered
output, not predicted — the closed-form chain (PROSPECT → white balance → CCM → tone curve)
reproduces in the renderer.

## Canopy age pinned

Direct measurement of canopy top height per age, against the real 0.54 m:

| age | canopy top | working distance |
|---|---:|---:|
| **40** | **0.525 m** | **1.115 m** |
| 45 | 0.621 m | 1.019 m |
| 60 | 0.651 m | 0.989 m |
| 75 | 0.746 m | 0.894 m |
| **real** | **0.54 m** | **1.10 m** |

`canopy.age 40` puts the camera 1.115 m above the canopy against a measured 1.10 m — a 1.4 %
GSD error, closing the 1.27× object-size gap.

## Gotcha worth keeping: the Vulkan fallback fails silently

The login node has no CUDA, so cmake selects the radiation plugin's Vulkan software-BVH
backend. That backend returns **NaN for every camera pixel** once plant geometry is present —
no error, just a black JPEG. Ground-only scenes render fine, which makes it easy to
misdiagnose. Always build and run on a GPU node; `scripts/env.sh` pins the CUDA path and
`scripts/gpu_test.sh` builds into a separate `build-gpu/` tree.

## Still open

- **Canopy cover 0.55 vs real 0.975.** Plants are too sparse; `canopy.germination_fraction`
  and `plant_spacing_y` are the levers, but raising density also raises canopy height, which
  is now pinned — these need tuning together.
- **Foliage brightness** (61,75,31) vs real (89,110,45) — exposure, not colour; the ratios
  already match.
- **Soil is a flat untextured tile.** Real soil has clods, cracks and shadowing. Currently a
  uniform spectrum on a flat plane, and visibly so.

---

# Canopy cover gap

## It was two gaps, not one

The headline "synthetic 0.55 vs real 0.975 cover" conflated a density gap with a tile-selection
policy. Measured on the real full frames:

| | vegetation cover |
|---|---:|
| real FULL FRAME (2023-07-28, rover edges excluded) | 0.838 |
| real FULL FRAME (2023-08-28) | 0.912 |
| best 640x640 crop obtainable from the 07-28 frame | 0.979 |
| fraction of its crops reaching the real tile median (0.975) | **1.7 %** |
| real 640x640 TILES (the training set) | **0.975 median** |

The real tiles sit in the extreme upper tail of what their own frames offer — they were
**selected** toward the densest regions. Chasing 0.975 by densifying the synthetic field would
have over-densified it relative to the actual field. The fix is: raise field density to the real
FRAME-level cover, then reproduce the tile SELECTION.

## Density

`canopy.rows` is now configurable (was hard-coded to 2). Sweep at age 40:

| rows | germ | spacing_y | plants | canopy top | frame cover |
|---:|---:|---:|---:|---:|---:|
| 2 | 0.7 | 0.13 | 15 | 0.532 | 0.632 |
| 3 | 0.7 | 0.13 | 24 | 0.537 | 0.796 |
| 4 | 0.7 | 0.13 | 33 | 0.548 | 0.815 |
| 3 | 1.0 | 0.13 | 36 | 0.538 | 0.894 |
| 4 | 1.0 | 0.09 | 68 | 0.534 | 0.933 |

**Canopy top stays 0.52–0.55 m across 15 to 68 plants** — density and height are independent
(no competition is modelled), so density can be raised without disturbing the pinned GSD.
Settings: `rows 3`, `germination 0.85`, `spacing_y 0.11` → frame cover 0.84–0.90.

## Phenology conflict, found and resolved

The library's cowpea flowers at day 40 and only reaches realistic flower density around day 75 —
by which point the canopy is 0.746 m against a real 0.54 m. **The model grows too tall relative
to when it flowers**, while real cowpea is flowering heavily *at* 0.54 m. Phenology is now
exposed; advancing `time_to_flower_initiation` reconciles them (12 → 87 boxes/frame,
18 → 41, 24 → 12, 30 → 0). Set to 14.

## Tiler

`syn2real/tile.py` cuts 640x640 tiles at **native resolution** — no resampling, so the measured
0.440 mm/px GSD is preserved exactly. It selects tiles by inverse-transform sampling against the
real cover quantiles (`widen` > 1 inflates the spread, which the asymmetric objective rewards),
re-encodes at JPEG quality 75 (the measured real quantization) and adds matched sensor noise.

Correction to an earlier claim in this document: the real pipeline does **not** drop
edge-truncated boxes. 7.43 % of real boxes touch the tile border (vs 14.97 % synthetic). The
earlier "real drops them" reading came from a per-*image* median of 0, which is 0 only because
most tiles have no border box at all. The tiler keeps truncated boxes above a
`min_visible` area fraction.

## Result

| statistic | real | synthetic OLD | synthetic NEW |
|---|---:|---:|---:|
| veg cover p5 | 0.780 | 0.730 | **0.803** |
| veg cover median | 0.971 | 0.933 | **0.946** |
| `veg_hue_deg` W1/IQR | — | 3.74 | **0.83** |
| `sat_mean` W1/IQR | — | 1.70 | **0.54** |
| `obj_size_px` | 33.0 | 26.1 | **31.5** (verdict WIDER-OK) |

## A regression this introduced, and its fix

Closing the colour gap with the CCM broke the dynamic range. The matrix's negative off-diagonals
drive dark pixels below zero, where `lin_to_srgb`'s `fmaxf(0,v)` clamps them to pure black:

| | pure black | >=250 | L p05 | L std |
|---|---:|---:|---:|---:|
| real | 0.00 % | 0.09 % | 22.6 | 15.5 |
| synthetic OLD | 0.07 % | 0.07 % | 17.1 | 15.7 |
| synthetic NEW, before fix | **2.19 %** | **2.28 %** | **1.0** | **27.0** |
| synthetic NEW, after fix | 0.00 % | 0.00 % | **22.7** | 23.5 |

A real sensor has a black-level offset and a noise floor and cannot produce a true zero.
`post.black_level 0.035` restores that floor (L p05 22.7 vs a real 22.6 — exact);
`post.highlight_knee 0.55` removes the highlight clipping.

## Still open

- **`L_std` 23.5 vs a real 15.5.** Driven by the soil-to-canopy brightness ratio: real soil sits
  at L 59.6 against a median of 49.6 (1.20x), synthetic at 97 against 52.9 (1.84x).
  - `post.contrast` is the WRONG lever — reducing it fixes `L_std` but lifts shadows far past
    real (L p05 22.7 → 49.0 at contrast 0.70) and collapses saturation.
  - `soil.reflectance_scale` is the right lever but is currently **masked by
    `post.highlight_knee`**, which compresses everything above 0.55 and so absorbs the change
    (0.35x scale moves soil L only 97.3 → 86.3). These two must be tuned jointly, or the knee
    replaced with a highlight treatment that does not flatten the soil.
- Flower count 5.08 boxes/tile vs a real 7.57.
- Tile cover upper tail: p95 0.974 vs a real 0.996.

---

# Canopy cover gap: closed

Final tile statistics, 150 tiles from 6 full-resolution renders:

| | real | synthetic OLD | synthetic FINAL |
|---|---:|---:|---:|
| tile cover p5 | 0.807 | 0.730 | **0.806** |
| tile cover median | 0.975 | 0.933 | **0.971** |
| `veg_cover_frac` verdict | — | MINOR | **OK** |

Several other statistics landed exactly along the way:

| statistic | real | synthetic FINAL |
|---|---:|---:|
| `local_rms_contrast` | 8.05 | **8.05** |
| `L_p05_shadow` | 20.78 | **20.78** |
| `obj_size_px` | 33.0 | **33.4** (WIDER-OK) |
| `veg_hue_deg` | 84 | **82** (W1/IQR 3.74 → 0.64) |

Verdict counts: SHIFTED 17 → 14, OK 0 → 2, WIDER-OK 3 → 5.

## What the shadow investigation actually found

The 28.6 % of pixels below L=10 were **not** a colour-matrix artifact. Rolling the CCM off in
the shadows changed the dark fraction by exactly nothing across every setting tried, which is
what ruled the matrix out. Two further hypotheses died the same way:

- **Scattering depth 2 → 8: no effect at all.** Correct physics — leaves absorb strongly in the
  visible, so second and third bounces contribute ~1 %. Multiple scattering matters in NIR, not RGB.
- **Side-light ratio 0.2 → 0.6: no effect.**

The cause was source **geometry**: six 0.1 × 0.08 m emitters at 1.6 m are near-point sources and
cast hard-edged shadows. `light.source_scale` now scales the emitters; 2.0 with a small diffuse
fill (`light.diffuse_flux 0.10`) is the colour-optimal point (G/B 2.42 against a real 2.43).

## The lift had to preserve chroma

A black-level pedestal added per channel matched the real shadow floor exactly (L p05 22.7 vs
22.6) but moved every colour toward grey. A fifth of the image desaturated, those pixels then
failed the excess-green test, and apparent canopy cover fell 0.96 → 0.82. Scaling all three
channels by a common factor instead raises luminance while leaving channel ratios untouched:

| lift | %L<10 | L p05 | cover | G/B |
|---:|---:|---:|---:|---:|
| 0.000 | 0.105 | 4.7 | 0.875 | 2.42 |
| **0.030** | **0.000** | **21.6** | **0.877** | **2.45** |
| real | 0.006 | 22.6 | 0.971 | 2.43 |

## Tiler bug found

The tiler was JPEG-encoding **twice** (`jpeg_roundtrip` then `imwrite`). The second pass scrubbed
the injected sensor noise, which is why the measured level stuck near 1.3 regardless of how much
was added. Fixed to a single encode, matching the real pipeline.

## Remaining gaps, and what they are NOT

- **`L_std` 19.4 vs a real 15.3** — improved from 27.8 but not closed.
- **Soil appearance is now the dominant residual**: `soil_hue_deg` 84° vs a real 40°,
  `soil_L` 94 vs 60, `soil_sat` 0.05 vs 0.25. The soil renders as bright desaturated green-grey
  rather than tan — the CCM's green boost applied to a near-neutral tan. Soil is only ~3 % of
  tile pixels, so its effect on a detector is limited, but it is the clearest remaining defect.
- **`specular_frac` 0.04 vs a real 0.005** — a side effect of enlarging the emitters.
- **`noise_sigma` 1.2 vs a real 2.2 — do not chase this by injecting noise.** The Immerkaer
  estimator uses a Laplacian kernel and therefore measures high-frequency *content*, which is
  conflated with sharpness. Adding white noise saturates at ~1.7 because JPEG q75 removes it;
  spatially-correlated noise did *worse*, because it has less high-frequency energy by
  construction. The real lever is render sharpness (`camera.samples`, `lens_diameter`), where
  synthetic already trails real (`edge_sharpness` 2.15 vs 2.55).
- **Flower count 5.4 boxes/tile vs a real 7.57.**

## Hand-tuning has reached its limit

Every remaining lever is coupled. Enlarging the light sources fixes shadows and raises cover but
drives G/B from 2.47 to 4.92. Reducing contrast fixes `L_std` but lifts shadows past real and
collapses saturation. Darkening the soil is masked by the highlight knee. These parameters cannot
be set one at a time — which is precisely the case for the joint optimizer in Phases 4–5 of the
plan. The coupling is now demonstrated rather than assumed, and the parameters and their measured
sensitivities are the screened short list that phase needs.
