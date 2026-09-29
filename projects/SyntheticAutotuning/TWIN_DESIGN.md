# Single-image digital twin — design notes

Written 2026-09-11. Companion to `PHASE1_FINDINGS.md` (the distribution-matching project) and
`HANDOFF_plant_model_lessons.md`. This document records the problem, what the literature says
about it, the architecture chosen, what is implemented in `twin/` and `main.cpp`, and what has
been measured so far. Numbers are updated as the work proceeds.

## 1. The problem

Given ONE real nadir frame from the T4 rover, produce a Helios scene whose rendered image is as
close as possible to it. The previous project matched a *distribution* of synthetic tiles to a
*set* of real tiles; here every plant in the frame is a specific plant, and the objective is
per-image, not per-set.

The obstacle the user identified is real and is the crux: PlantArchitecture is stochastic and
non-differentiable, and seeding the Context RNG does not make the scene a stable function of its
parameters. Every random value the plant model draws — bud break, internode length, leaf
angles, which prototype a leaf gets — comes from the single `std::minstd_rand0` the Context owns
(`RandomParameter_float::resample()` in `PlantArchitecture.h`, plus a dozen direct
`context_ptr->randu()` calls in the growth loop). Grown together, plant 7's leaves depend on how
many draws plants 0–6 consumed, so one more node on plant 2 re-deals every plant after it. Brute
force ("render thousands, keep the best") treats the product of per-plant probabilities as one
lottery.

## 2. What the literature says (survey run 2026-09-11)

Three sweeps were run (inverse procedural modelling; stochastic-simulator fitting and
sim-to-real; canopy image-analysis tooling). The ideas that survived scrutiny:

1. **Address the randomness structurally, not serially.** Probabilistic-programming trace
   semantics (Wingate et al. 2011; Gen's `regenerate`; Pyro `poutine.trace`) name every random
   choice by its position in the program so that changing one choice leaves the rest fixed.
   Counter-based / hash RNGs (Random123, Houdini `rand(@ptnum)`, JAX key splitting) give the same
   property for free: `value = hash(seed, address)`. Klein et al. 2024 apply exactly this to
   agent-based simulations with births and deaths (per-agent streams; >10× fewer runs for a
   given standard error). Talton et al. 2011 (Metropolis Procedural Modeling) and Ritchie et
   al. 2015/2016 (SOSMC, neurally-guided procedural models) do inference over such traces with
   trans-dimensional moves, which is what "organ count changes" needs.
2. **Exploit locality.** In a nadir image a plant's likelihood is nearly separable by footprint.
   Yeh et al. 2012 anneal per object. Fixing plant positions from the photo (CropCraft, 2024)
   removes the largest source of structural randomness.
3. **Two losses for two stages.** Parameters are identified from *statistics* (Stava 2014;
   CropCraft's depth/extent histograms; Wang 2020's pattern-oriented acceptance bands); the
   *realisation* is fitted afterwards with instance-level losses (mask IoU) with the parameters
   frozen. Mixing the two in one objective is what makes single-realisation fits unstable.
4. **Pin what is visible, hallucinate the rest from the prior** (Tan et al. 2008 single-image
   trees; Li 2021; Tree-D Fusion 2024). No single-image method in the literature matches
   leaf-level detail; all infer a scaffold and let the procedural prior finish. Helios already
   has `setPetioleLeafGeometry()` for prescribing a leaf's pose, "intended for the
   reconstruction workflow".
5. **Multi-fidelity, seed-matched.** Warne et al. 2025: cheap and expensive simulators must be
   coupled by the same realisation; a rasterized geometry pass and a full render of the same
   scene are coupled by construction.
6. **Amortised proposals are a later accelerator, not the foundation** (Ritchie 2016, Ellis
   2018, BayesSim, NPE): a CNN trained on the generator's own renders can propose parameters
   and realisations, but is only a proposal and is untested on real cowpea photos.
7. **Similarity without alignment**: DINOv2 patch features with sliced-Wasserstein or contextual
   loss, DISTS, DreamSim; never LPIPS on unaligned layouts. Once positions are matched, per-plant
   masked losses are legitimate.
8. **Tooling**: PhenoBench (nadir field robot, plant+leaf instances) is the closest public data;
   SAM-family proposals guided by a detector work, "everything" mode does not; Careaga & Aksoy
   `Intrinsic` gives a shading map to compare against a render rather than raw pixels.

## 3. Architecture

The scene is a union of independent plants (no competition is modelled) plus soil, camera and
lights. So:

    image = Camera(Lights, Soil, ∪_k Plant(θ, seed_k, position_k, yaw_k, age_k))

and the fit is staged, each stage using the cheapest instrument that can see its residual:

| stage | what is fitted | instrument | cost |
|---|---|---|---|
| 0 | camera (calibrated intrinsics, undistortion), rover exclusion mask, vegetation mask, rows, plant positions and footprints | real frame only | seconds |
| 1 | generator parameters θ that are identified by statistics (age→footprint curve; later leaf scale, petiole length) | CPU label rasterizer | 0.4 s per plant |
| 2 | layout: positions from the photo, one site per real plant | — | — |
| 3 | per-site realisation: seed and yaw by silhouette IoU against that plant's mask | CPU rasterizer, K·N single-plant passes, embarrassingly parallel | 0.4 s each |
| 4 | per-site refinement: age, yaw, position with the rest frozen | CPU rasterizer | 0.4 s each |
| 5 | appearance: lighting, soil, leaf optics, camera pipeline, with geometry frozen and therefore deterministic | ray tracer once per lighting candidate; Python developer for the post chain | GPU minutes / seconds |
| 6 | (planned) leaf-level pinning of visible leaves via `setPetioleLeafGeometry` | rasterizer | — |

### 3.1 Per-site random streams (implemented, `main.cpp`)

`canopy.per_plant_seed 1` reseeds the Context generator from `hash(site_seed, purpose)` before
each plant is built and again before it is grown, and grows plants one at a time with
`advanceTime(plantID, age)`. Plant k then depends on (θ, site_seed, age, position) only.
Verified: with two layouts that differ in one site's seed, the other 11 sites are reproduced
bit for bit (isolated site maps identical, 0 differing pixels), and the full-scene difference is
confined to the modified plant's footprint.

`canopy.layout_file` places plants explicitly: one `x y yaw_deg age_days seed` per line. The
grid path is unchanged when the option is off, so every earlier configuration still reproduces.

A subtlety found on the way: the plant's realised geometry depends on its base position at the
last floating-point bit — ground clipping tests `v.z < ground_height` per vertex, and a leaf
whose tip rests on the ground is clipped or kept depending on that comparison, which a one-ULP
move can flip (2,764 of ~20,000 pixels changed for a 3e-8 m move of one plant). A layout must
therefore record positions with float32 round-trip precision (`twin.raster.f32`), which it now
does; 4-decimal positions silently reproduce a different plant. Within-plant addressing (per
phytomer rather than per plant) is the natural next step and would be an upstream change to
PlantArchitecture; it is not needed for stages 1–5.

### 3.2 CPU label rasterizer (implemented, `main.cpp raster`)

A z-buffer over the same pinhole camera as the RadiationModel camera, honouring the leaf
cut-out textures through their transparency masks. Writes per-pixel site index, organ index,
class (ground/leaf/open flower/closed flower/stem/fruit/rover/none), depth and normal, as raw
arrays plus a JSON sidecar; `raster.crop 1` writes just the plant's bounding box; `raster.scale`
sets the working resolution; `raster.only_sites` isolates plants at their true place in the
frame. 0.14 s for a 12-plant scene at 648×512, ~1.8 s to build the plants.

Validated against the ray tracer: the same scene rendered with `output.write_site_ids 1` gives a
per-pixel site label map that agrees with the rasterizer's site map on 85 % of labelled pixels
with no flip or transpose, and 90 % of the disagreeing pixels lie within one pixel of a plant
boundary (the ray tracer integrates 20 jittered, lens-blurred samples per pixel; the rasterizer
takes the pixel centre). Interiors agree. The rasterizer therefore registers to the ray-traced
label maps directly; the JPEG the renderer writes is flipped relative to those maps and is
handled in Python.

### 3.2a Closed-canopy scoring (implemented, `twin/canopy.py`)

Once the mask saturates, a candidate plant is scored inside a window around its site by three
cues the rasterizer produces without light transport: vegetation IoU (the gaps), an edge term
(fraction of real Canny edges and synthetic organ boundaries with a counterpart within ~1 cm),
and the normalised cross-correlation between real luminance and synthetic n·z (a Lambertian
proxy for a light rig at nadir, i.e. leaf orientation). Occlusion couples neighbours, so a
candidate is composited by depth into the scene rasterized without that site, giving exact
full-scene maps per candidate at the cost of one single-plant pass. Unit test on a pseudo-real
target (cues taken from a rasterized scene with known seeds, six plants at 0.15 m spacing, age
40): the true plant scores 0.971, the true plant turned 15° 0.868, an empty site 0.868, and
eighteen alternative seed/yaw candidates 0.79–0.85. The IoU and edge terms were saturated in
that test (0.98–1.0, 0.94–1.0) and the shading term carried the discrimination (0.92 against
~0.5); the edge term has since been re-normalised as a hit fraction at a 1 cm tolerance.

Against a *ray-traced* pseudo-real target (a 36-plant, age-40 row layout rendered on the GPU;
luminance and Canny edges from its JPEG, vegetation from the label map), the picture is
weaker. Whole-frame score: truth 0.706, random seeds and yaws at the true sites 0.594, after one
coordinate-descent sweep 0.620 (75 min, 32 cores). The shading term for the *truth* is only
0.227 against 0.916 with raster-derived cues: lit foliage correlates weakly with n·z because of
shadows, specular highlights and inter-leaf shading, so the cue that carried the unit test is
largely gone on a real-looking image. The first run also could not measure seed recovery at
all — the true seed was never in a site's candidate pool, so "0 of 36 recovered" is by
construction, not a finding. The corrected run offered the true plant (and its 90/180/270°
turns) at each of twelve sites alongside 72 random candidates: **the truth ranked first at 3 of
12 sites**, and 5th to 77th of 77 at the others; scores across all candidates at a site spanned
only 0.60–0.69. (Caveat: only 12 of the target's 36 plants were in the fitted layout, so the
windows contain foliage from absent neighbours; the ranks are indicative, not clean.) The
conclusion stands: with these cues the score cannot tell the true realisation from random ones
on a lit image, so the closed-canopy stage needs a stronger cue before more search is worth
running — a shadowed shading estimate from the depth buffer and the known lamp positions, a
low-resolution ray-traced candidate image, or DINOv2 patch features — and the sparse-stage
lesson applies here too: the arrangement of leaves is better imposed from the photo than
searched for.

### 3.3 Real frames (implemented, `twin/real.py`)

Source: `/group/jmearlesgrp/GEMINI/heesup/dataset/2023_davis_cowpea_dataset/<date>/T4/Plot<NNN>-MAGIC<NNN>/camA/`,
eight dates 2023-06-20 … 2023-07-28, 504 plots per date, ~21 frames per plot, 2592×2048. The
tiles the previous project trained on were cut from the 2023-07-25 frames of these plots (the
parent of one training tile was located byte-for-byte). Plot286-MAGIC083 is the test plot: two
rows of separable seedlings on 06-20, rows filling by 07-03, closed and flowering by 07-25.

Camera: the rover configuration (`config/camA.pbtxt`, 2023-07-25 calibration session) carries a
PLUMB_BOB calibration: fx 1787.6 px, cx 1301.3, cy 1022.6, k1 −0.127, k2 0.055. That is an
8.6 mm lens, not the 12 mm the previous project inferred from the datasheet (HFOV 71.9° rather
than 54.8°), and the corners are bent inward by 7 %. Every real frame is undistorted to the
pinhole model at the calibrated fx before anything is measured, and the synthetic camera uses
that fx. Camera height: `rover_details.json` says 1.5 m; the previous project measured 1.64 m;
the SpyderCHECKR board on the soil in the 07-28 calibration frame (14.0 × 20.0 cm) gives 1.52 m
from its long side and 1.61 m from its short side. It is carried as a fit parameter, initial
1.55 m. The rover model in `Syn2Real_cowpea/obj` has structure near the camera height that the
real frames do not show, so it cannot be used to fix the height.

Rover mask: the rover is rigid relative to the camera, so the per-pixel temporal standard
deviation over 64 frames from different plots and dates isolates it (rails: std < 18 grey
levels; soil and plants: 22–38). Filled from the frame edge to the innermost rover pixel per
row; 20.8 % of the frame. Stored in `calib/rover_mask.npy`.

Vegetation: CIELAB a* < −8 with speckle removed; rows from the smoothed column profile of the
mask (two rows 811 px apart on 06-20); plants as connected components split along the row
direction where the component's width profile shows more than one peak.

### 3.4 Fitting (implemented, `twin/fit.py`, sparse stands)

Stage 1 builds an age→footprint table (single plant at the frame centre, 4 seeds per age,
11 ages) and inverts each real plant's footprint area to an age. Stage 3 rasterizes K seeds ×
12 yaws per site exactly (a 2-D rotation of the silhouette was tried first and mis-ranked
candidates for off-axis plants, where perspective displaces leaves by ~100 px per 0.2 m of
height). Stage 4 refines age (±3 d), yaw (±10°) and position (±2 cm). The objective per site is
the IoU of the candidate silhouette with the real plant's mask inside a neighbourhood one plant
radius wide, so foliage placed where the photo shows soil is charged.

## 4. Results so far

*(2023-06-20, Plot286-MAGIC083)*

| run | plants | per-site IoU (min / median / max) | scene IoU | precision | recall | cost |
|---|---|---|---|---|---|---|
| v1: unsplit components, 2-D yaw approximation | 10 | 0.10 / 0.35 / 0.49 | 0.368 | 0.52 | 0.56 | 278 s, login node |
| v2: row-split plants, exact yaw sweep, refinement | 16 | 0.28 / 0.44 / 0.53 | 0.475 | 0.61 | 0.68 | 952 s, 32 CPUs |
| v3: v2 under the Stage-1 optimiser's parameters (§4.2) | 16 | 0.30 / 0.53 / 0.57 | **0.517** | 0.61 | 0.78 | 121 s, 32 CPUs |

*Four more frames, same code and the same optimised parameters (fitted on 06-20 Plot286 only):*

| frame | cover | plants | scene IoU | precision | recall | cost |
|---|---|---|---|---|---|---|
| 2023-06-20 Plot201-MAGIC262 | 0.096 | 17 | 0.564 | 0.69 | 0.75 | 105 s |
| 2023-06-27 Plot286-MAGIC083 | 0.182 | 14 | 0.609 | 0.72 | 0.79 | 175 s |
| 2023-06-27 Plot298-MAGIC226 | 0.234 | 19 | 0.690 | 0.80 | 0.83 | 220 s |
| 2023-07-03 Plot286-MAGIC083 | 0.335 | 15 | 0.636 | 0.85 | 0.72 | 242 s |

The parameters transfer to other plots and a week later without refitting. Scene IoU rises with
cover, which is partly genuine (older plants have more leaves and a smoother outline) and partly
the metric (a larger mask is easier to overlap); the 07-03 frame's lower recall shows the
splitter starting to merge neighbours as rows fill.

v1's failure modes were visible in the overlay: touching seedlings had merged into single
components and been fitted as one older plant each, and the approximate yaw ranking overstated
the per-site IoU by up to 0.3 (perspective displaces a leaf at 0.2 m height by ~100 px at the
frame edge, which a 2-D rotation of the silhouette does not reproduce). v2 fixes both; the
refinement stage moved 9 of 16 sites by 1–2 days of age or 10° of yaw for +0.01 to +0.10 IoU.
The remaining gap is the seedling model itself (§4.1).

### 4.0 Appearance: first pass on the fitted 06-20 scene

The ray-traced render of the fitted layout (2592×2048, 40 samples, 1.9M primitives) took
3.7 GPU-minutes — far below the 50 minutes the previous project quoted, which was for the
10M-primitive OBJ leaf meshes. Developed from the raw EXR with the scene-fit colour matrix and
a gain that puts synthetic foliage at the real foliage L*, the masked statistics were:

| | real | synthetic | note |
|---|---|---|---|
| foliage L* / a* / b* | 44.3 / −17 / +27 | 44.1 / −17 / +16 | hue right, yellow deficient |
| foliage L* p10–p90 | 35–55 | 14–59 | synthetic shadows too deep |
| soil L* / a* / b* | 42.4 / 0 / +16 | 62 / −1 / +3 | soil too bright, grey, flat |

Re-rendered under the optimised parameters (v3 layout): vegetation fraction 0.088 against
0.087 real, foliage L* 44.3 / a* −16 / b* +15 against 44.3 / −17 / +27, soil unchanged. The
geometry now fills the right pixels; what remains is appearance (leaf yellowness, shadow depth,
soil colour and texture). One more appearance defect has a known cause: the blocky shadow halos
around the seedlings are the ground tile's 250×250 sub-patches (1.2 cm, ~14 px) — the camera
reads radiance per primitive, so soil shadows are quantised to the patch. `scene.ground_subdiv`
now exposes it; 750–1000 brings the patch to the pixel scale at a cost of up to a million ground
primitives (not yet rendered).

Two findings on the way. (1) **Correction (2026-09-11, afternoon).** The magenta renders and the
"white balance applied twice" diagnosis were my scene error, not a Helios change: the twin
render script had `scene.load_rover 0`, so the calibrated collimated sun lit the plot unshaded,
and the five-variant bisection carried the same setting. With the T4 body loaded — it shrouds
the plot over the LED rig, as in the real rig — the raw radiance is a hundred times lower and
its balance is what the previous project calibrated for: foliage G/R 1.86, G/B 2.24 raw, and the
illuminant-aware white balance (1.563 / 1 / 1.596) with the colour-board matrix puts foliage at
L*/a*/b* 44/−18/+25 against the real 44/−17/+27 and soil at 39/−3/+10 against 42/0/+16. On the
unshaded sun-lit render that same balance over-corrects, which is where the magenta came from.
The sun shadows in the earlier renders had the same cause. Renders now load the rover, use
`camera.flux_smoothing 30` (`enableCameraFluxSmoothing`, which interpolates radiance across
shared vertices and removes the per-facet steps) and a 6 mm ground tiling.
(2) Soil
radiance is linear in soil reflectance, so soil brightness is fitted on the CPU by scaling the
ground pixels of the raw EXR: `soil.reflectance_scale` 0.09 puts soil L* on target, but b*
stays at +2 against +16 — the library soil spectrum is too neutral, and the soil is a flat
untextured tile. A render sweep over the five library soil spectra changed nothing: they are
near-identical in the visible (650/450 nm reflectance ratio 1.34–1.35 for all five), so
`soil.spectrum_index` is not a lever. For a twin of one frame the soil is a directly observed
static background,
and the cleanest fix is to use the real frame's soil pixels themselves (illumination divided
out, occluded pixels inpainted) as the ground albedo texture.

### 4.1 The seedling model is the ceiling, not the seed

A panel of the six largest real plants on 06-20 (25–38 cm across) beside model plants of the
same footprint (ages 8–18) shows the mismatch that caps the per-plant IoU near 0.5: the real
seedlings are rosettes of many small leaflets (roughly 4–6 cm), the model's are a handful of
leaflets two to three times that size on long petioles. Age cannot fix that — it scales leaf
number and size together — so leaf prototype scale, phyllochron and petiole length have to be
fitted first, at this growth stage where every plant is seen whole. `scripts/twin_stage1_screen.py`
does that as a grid over the three, scoring each combination by the best per-plant IoU a
reduced seed/yaw search can reach.

### 4.2 Stage 1 as the outer loop (implemented, `twin/stage1.py`, `scripts/twin_stage1_opt.py`)

Agreed on 2026-09-11 after the point was raised that the fit so far only searched site-level
variables (position, yaw, age, seed) of the default model — a plant that matches by coincidence.
The restructure: the generator's shape parameters are the outer loop, optimised by Optuna TPE
over twelve variables (leaf scale min and width, petiole length min and width, petiole pitch
min and width, leaf pitch spread, phyllochron, internode length, the two Beta leaf-angle
parameters, camera height), with the library defaults enqueued as trial 0. The objective for a
parameter vector is the mean, over eight real plants spanning the size range, of the best
silhouette IoU that a *fixed* set of 6 seeds × 8 yaws reaches for that plant; the seeds are the
same for every trial (common random numbers), so trials are compared on paired draws and the
inner seed search is "best achievable" — a placeholder for the leaf-level stage, not the answer.

Three changes made a trial cost 6–12 s instead of 390 s. The binary links OpenMP and every
raster process spawned a thread per core, so a pool of them oversubscribed the node about
twenty-fold (64 plants across four processes: 24.7 s with the default thread count, 1.2 s with
`OMP_NUM_THREADS=1`); the runner now pins one thread per process, and every earlier sweep in this
project — the sparse fits, the pseudo-real tests, the grid screen — had been paying that cost.
`raster.each_site 1` builds and draws every site of a layout alone, cropped, in one process:
16 plants in 2.3 s, bit-identical to the single-plant path, where the same 16 as separate
processes cost 15–30 s (start-up and asset loading dominate); the sparse fit's candidate sweeps
go through it too. And the leaf-angle distribution option
(`leaf.set_angle_distribution`, `leaf.angle_beta_*`) had been nested inside the nitrogen block
and was silently skipped whenever that model was off; it is now applied for any configuration
(mean inclination 35.7° planophile against 43.8° default, measured on the proxy).

The coarse grid that preceded the optimiser (leaf scale × phyllochron × petiole length, 27
cells, three plants) had already said the defaults are wrong for seedlings: short petioles
(0.04–0.07 m) with 0.07–0.10 m leaves reach 0.39–0.41 best per-plant IoU, the library-like cells
0.26–0.35.

**Result (120 trials, 18 min on 32 cores).** Objective 0.423 for the library defaults →
**0.515** at the best trial, per plant 0.47–0.58 against 0.36–0.51 before. What the top ten
trials agree on, and what they do not:

| parameter | library / previous | top-10 median (range) | identified? |
|---|---|---|---|
| petiole length (m) | 0.10–0.14 | 0.024–0.064 (0.020–0.066) | yes: 2–3× shorter |
| internode length max (m) | 0.025 | 0.013 (0.010–0.019) | yes: half |
| leaf prototype scale (m) | 0.10–0.16 | 0.096–0.137 (0.068–0.165) | no change |
| phyllochron (d) | 2.0 | 2.3 (1.0–2.9) | not identified |
| leaf pitch spread (°) | 20 | 24 (4.6–38) | not identified |
| leaf angle Beta μ, ν | 1, 1 (uniform) | 1.7, 1.1 (0.96–2.44, 0.84–2.53) | weakly |
| camera height (m) | 1.55 | 1.62 (1.49–1.66) | not identified |

So the seedling silhouette pins the compactness of the plant — how far the leaflets sit from
the stem and from each other — and is indifferent to the rest at this resolution; those need
the leaf-level stage (or the closed-canopy frames) to be identified. The objective is
deterministic under the paired seeds (a resumed run reproduced earlier trials to four decimals),
and a trial costs 6–12 s, so the search can afford a finer inner budget (more seeds and yaws)
when the ceiling matters.

### 4.3 Five frames rendered with the calibrated scene

Developed with the corrected chain (§4.0), masked statistics real → synthetic:

| frame | foliage L*/a*/b* | soil L*/a*/b* | scene IoU |
|---|---|---|---|
| 06-20 Plot286 | 44/−17/+27 → 44/−18/+25 | 42/0/+16 → 42/−3/+11 | 0.517 |
| 06-20 Plot201 | 44/−18/+30 → 44/−18/+25 | 43/−1/+16 → 42/−4/+11 | 0.564 |
| 06-27 Plot286 | 46/−18/+28 → 46/−18/+26 | 44/+1/+13 → 44/−4/+11 | 0.609 |
| 06-27 Plot298 | 44/−19/+34 → 44/−18/+25 | 44/+1/+14 → 44/−4/+11 | 0.690 |
| 07-03 Plot286 | 48/−17/+23 → 48/−19/+26 | 47/+1/+12 → 47/−4/+11 | 0.636 |

Three-pane figures (real | synthetic | real with synthetic masks) in `twin_work/<frame>_opt/three_pane.jpg`
and in the report. Two things the figures show that the numbers do not: the 07-03 synthetic
plants carry flowers the real plants do not have yet (footprint-matched model ages 30–46 d with
flower initiation at 19 d, tuned for the closed canopy: model age and calendar age disagree,
and phenology has to be fitted at this stage), and the rendered rover body comes out much
brighter than the real rails (it is masked out of every comparison, but it is wrong).

### 4.4 The real soil as the ground albedo (implemented, `twin/soil.py`, `scene.soil_albedo_map`)

Soil pixels of the real frame are run backwards through the development chain (sRGB → linear
→ inverse colour matrix → inverse white balance), scaled so the median soil reflectance equals
the calibrated scalar (library soil × the fitted 0.09 scale), inpainted where plants (grown by
20 px so mixed edge pixels do not bleed in) and the rover hide the soil, and resampled over the
bed through the pinhole into a 512×512 map. `main.cpp render` samples it at every ground
sub-patch centre and sets per-band `reflectivity_red/green/blue`, which the radiation model
takes in place of a spectrum. Two caveats: the temporal-std rover mask misses the bright inner
rail blocks and the tyres, so a fuller mask (`calib/rover_mask_full.npy`, std ∪ low-chroma/dark
pixels in the outer bands, filled from the frame edge; 42 % of the frame) is used for this
purpose only; and the photo's own shading is baked into the albedo, so the twin's soil carries
the real frame's shadows under the render's own.

First render with it (06-20 Plot286): the soil has the real frame's texture and cracks and its
lightness spread matches (L* p10–p90 31 wide against 27 real), the foliage b* moved from +25 to
+27 (real +27, via the brighter yellower soil bounce), but the soil was too bright (L* 64
against 42): the map's median reflectance was set by analogy to the library spectrum, and a
flat per-band reflectance behaves differently through the model. The fix is the same trick as
before — soil radiance is linear in reflectance, so the factor is fitted on the EXR and the map
rescaled (factor 0.384, median reflectance 0.0156). With that, all five frames rendered with
their own soil, real → synthetic (L*/a*/b*):

| frame | foliage | soil | masked colour distance (flat tile → own soil) |
|---|---|---|---|
| 06-20 Plot286 | 44/−17/+27 → 44/−19/+27 | 42/0/+16 → 42/−2/+19 | 4.2 → 2.7 |
| 06-20 Plot201 | 44/−18/+30 → 44/−18/+25 | 43/−1/+16 → 43/−2/+19 | 3.5 → 2.3 |
| 06-27 Plot286 | 46/−18/+28 → 46/−18/+26 | 44/+1/+13 → 44/0/+16 | 3.1 → 2.1 |
| 06-27 Plot298 | 44/−19/+34 → 44/−18/+25 | 44/+1/+14 → 44/−1/+16 | 5.3 → 4.1 |
| 07-03 Plot286 | 48/−17/+23 → 47/−19/+26 | 47/+1/+12 → 47/0/+16 | 4.9 → 4.1 |

The soil's lightness spread now matches the real one (p10–p90 31–53 against 26–53 on 06-20)
and the shadow depth under leaves closed (foliage p10 30 against 35). Two smaller defects
remain: the inpainted band beside the rails is smeared, and the rendered rover is far brighter
and greener than the real one (its frame reflectance carries a 1.3× scale from the earlier
project). The remaining foliage residual is the yellow axis on the yellowest plots (b* +25
against +30 to +34), which is leaf optics, not soil.

### 4.5 Identifiability from silhouettes (`scripts/twin_identifiability.py`)

Synthetic targets with known parameters (the real 06-20 layout's positions and ages, fresh
seeds and yaws) were rasterized and handed to the Stage-1 optimiser exactly as a real frame's
mask would be, with the true per-plant masks from the site map. Two truths, 120 trials each,
recovery measured on the top 10 % of trials in units of the search range:

| parameter | truth = optimiser winner: bias / spread | truth = random draw: bias / spread |
|---|---|---|
| leaf scale min | +0.10 / 0.20 ✓ | **+0.78** / 0.25 ✗ |
| leaf scale width | −0.27 / 0.63 ✗ | −0.33 / 0.46 ✗ |
| petiole length min | −0.09 / 0.18 ✓ | −0.34 / 0.28 ✗ |
| petiole length width | −0.24 / 0.38 ✗ | −0.59 / 0.34 ✗ |
| petiole pitch min | −0.17 / 0.81 ✗ | −0.66 / 0.38 ✗ |
| petiole pitch width | −0.05 / 0.35 (weak) | −0.01 / 0.46 ✗ |
| leaf pitch spread | −0.17 / 0.54 ✗ | −0.10 / 0.34 ✓ |
| phyllochron | −0.04 / 0.52 ✗ | +0.17 / 0.24 (weak) |
| internode length | +0.01 / 0.08 ✓ | −0.17 / 0.19 (weak) |
| leaf angle μ | +0.13 / 0.33 ✓ | +0.31 / 0.41 ✗ |
| leaf angle ν | +0.35 / 0.28 ✗ | −0.46 / 0.51 ✗ |
| camera height | +0.48 / 0.45 ✗ | −0.34 / 0.79 ✗ |

Two readings. First, the optimiser beats the truth on its own objective in both runs (0.622 vs
0.592; 0.461 vs 0.382): the best-of-six-seeds silhouette IoU is limited by which realisations
happen to be in the pool, and other parameter sets exploit the pool better than the truth does.
Second, and more important for "picture → model": in the random-truth run the optimiser
recovered a *different plant* — leaves 2.4× larger and petioles half as long as the truth —
that matches the silhouettes better than the truth. Leaf size and petiole length compensate in
a footprint, so **silhouettes identify compactness (internode length, and leaf size × petiole
length jointly) and little else**. The four parameters recovered in the first run were
recovered because the truth sat where the real fits sit, not because the observable pins them.
This is the case for leaf-level observables (leaflet size and count from masks, visible
petiole length) and for a statistics-based objective rather than best-of-seeds IoU, before any
calibrated parameter is quoted as a property of the crop.

### 4.6 Three things the eye picked up (user, 2026-09-11) and what they measure as

1. **Synthetic leaves too large.** Confirmed by inscribed-disc leaflet half-widths on the
   masks: real median 15 / 17 / 21 mm on 06-20, 06-27, 07-03 against synthetic 20 / 33 / 35 mm,
   with 3–7× fewer leaflet peaks. Exactly the compensation the identifiability test predicted
   (leaf size × petiole length). Leaflet width and count are now terms in the Stage-1 objective
   (`twin.stage1.leaflet_stats`, |log ratio| per plant, weights 0.30 and 0.15 against IoU).
   Rerun (120 trials, 23 min): score 0.236 → 0.289 (IoU 0.423 → 0.437, width penalty 0.35 →
   0.25, count penalty 0.55 → 0.48), and the answer flipped to the other side of the
   compensation: leaflets 5.3–10.5 cm (was 9.3–14.4), petioles 8–12 cm (was 4–6.5),
   phyllochron 0.96 d (was 2.7, i.e. nearly three times as many nodes), internode 0.015 m.
   The top ten agree on leaflet scale (min 0.046–0.10, max 0.095–0.12), petiole length
   (0.06–0.10 / 0.09–0.12) and phyllochron (median 1.0); the leaf-count penalty stays large
   because the model cannot put more than three leaflets on a node and the peak counter also
   counts lobes and curls on real leaves. Refits of the five frames under these parameters
   (leaflet half-width median in mm / peak count; per-plant IoU median):

   | frame | real | silhouette-only fit | leaflet-aware fit |
   |---|---|---|---|
   | 06-20 Plot286 | 15 / 253 | 20 / 91, IoU 0.53 | 11 / 280, IoU 0.45 |
   | 06-20 Plot201 | 15 / 246 | 18 / 137, IoU 0.58 | 11 / 321, IoU 0.48 |
   | 06-27 Plot286 | 20 / 297 | 40 / 65, IoU 0.51 | 16 / 267, IoU 0.49 |
   | 06-27 Plot298 | 17 / 410 | 33 / 91, IoU 0.56 | 16 / 429, IoU 0.50 |
   | 07-03 Plot286 | 21 / 472 | 35 / 63, IoU 0.53 | 24 / 318, IoU 0.48 |

   Leaflet size and number now match to within about 25 % on every frame where they were
   1.3–2× and 3–7× off, at a cost of 0.03–0.08 in per-plant silhouette IoU (scene IoU 0.48 /
   0.50 / 0.58 / 0.61 / 0.62 against 0.52 / 0.56 / 0.61 / 0.69 / 0.64). That is the trade the
   objective was asked to make: the plant is now the right kind of plant, and the silhouette
   overlap it loses is the part that only a matching realisation (leaf-level pinning) can give.
   Rendered with each frame's own soil and chlorophyll and specular 0.02 (`render_soil/` in the
   `*_leaf` work directories): foliage b* 30/32/31/35/27 against 27/30/28/34/23 real, a* −21 to
   −22 against −17 to −19, soil within 1–4 units; masked colour distance 3.6 / 3.4 / 3.4 / 1.8 /
   4.4. The a* offset is systematic and small; a carotenoid or chlorophyll offset on the
   calibration curve would close it.
2. **Specular too strong.** It is on at the previous project's `leaf.specular_scale 0.08`,
   `leaf.specular_exponent 35`, calibrated for the closed canopy under the earlier lighting; the
   LED rig near nadir puts highlights on camera-facing leaves that the real frames barely show.
3. **Leaf colour is global, not per frame.** Every render used the nitrogen model with its
   target of 3.4 g N/m², which puts every leaf at chlorophyll 68 with no spread; the real
   Plot298 seedlings are visibly yellower. Leaf optics have to be calibrated per frame as part of
   the model. A chlorophyll {20, 30, 40, 55} × specular {0.08, 0.02} render grid on that frame
   (`scripts/twin_leafgrid.sh`, evaluated by `scripts/twin_leafgrid_eval.py`) gave, at
   specular 0.02, foliage a*/b* of −11/+49, −16/+47, −19/+41, −21/+34 for chlorophyll 20, 30,
   40, 55 — monotonic, so each frame's chlorophyll is read off that curve from its own foliage
   colour (70, 64, 68, 55, 78 for the five frames; `<workdir>/leaf_overrides.txt`, taken up by
   the render script). Specular 0.02 was chosen by eye: at 0.08 the leaf faces carry a sheen the
   real matte leaves do not have, and the highlight statistics did not separate the two. Rendered
   with these, foliage b* matches on every frame (28/30/30/34/26 against 27/30/28/34/23) and a*
   sits 2–4 units greener than real; Plot298's masked colour distance fell to 1.6.

### 4.7 The rover body (user, 2026-09-11)

The rendered T4 body was far lighter than the real one. Measured on the 06-20 frame over the
pixels both masks call rover: real L* 32 (p10–p90 18–45), rendered 70 (45–81); in linear
radiance the rendered body was 5.5× the real with the same hue (per-band ratio real/synthetic
0.183 / 0.168 / 0.171). The body sits within a metre of the LED rig, and the earlier project's
1.3× frame scale was set under different lighting. The three material scales are now config
keys (`scene.rover_frame_scale`, `scene.rover_fender_scale`, `scene.rover_tyre_scale`; the tyre
one is new, on a copy of the dark-grey board spectrum) and the twin renders pass 0.17× the
previous values (0.22, 0.13, 0.17). Re-rendered: rover pixels L* 33 (p10–p90 18–40) against
the real 32 (18–45), a*/b* −4/+5 against −2/+7. Darkening it also removed the light it had been
bouncing onto the plants and soil: foliage a* moved 1–2 units toward real on every frame and
the masked colour distances fell from 3.6 / 3.4 / 3.4 / 1.8 / 4.4 to 2.5 / 1.8 / 2.5 / 1.3 / 3.2.

### 4.8 Naive baseline (user, 2026-09-13)

What the scene looks like with none of this harness: `canopy.library_defaults 1` (new; skips every
shoot-parameter and phenology override in `buildCanopy`), a grid layout from
`scripts/twin_baseline_layout.py` (two rows at 0.76 m, 0.15 m in-row, 80 % germination, uniform
age from an assumed planting date of 2023-05-31 — the dataset's `planting_date` is null), the rig
as documented (rover body, calibrated lens, 1.5 m), stock appearance (library soil unscaled,
LeafOptics default pigments, no specular, default rover reflectance, Helios auto exposure and auto
white balance, no colour matrix) and the twin's render quality. Rendered by
`scripts/twin_render_baseline.sh`; compared by `scripts/twin_baseline_gallery.py`, which writes
four-pane figures (real | baseline | twin | twin masks on real) and `twin_work/report/baseline_vs_twin.json`.

| frame | cover real / baseline / twin | scene IoU baseline → twin | foliage L*/a*/b* real / baseline / twin |
|---|---|---|---|
| 06-20 Plot286 | 0.087 / 0.207 / 0.094 | 0.26 → 0.46 | 44/−17/+27 · 31/−12/+15 · 44/−21/+27 |
| 06-20 Plot201 | 0.094 / 0.207 / 0.097 | 0.23 → 0.49 | 44/−18/+30 · 31/−12/+15 · 43/−20/+29 |
| 06-27 Plot286 | 0.179 / 0.424 / 0.173 | 0.27 → 0.56 | 46/−18/+28 · 33/−13/+15 · 46/−21/+29 |
| 06-27 Plot298 | 0.231 / 0.424 / 0.219 | 0.35 → 0.60 | 44/−19/+34 · 33/−13/+15 · 44/−20/+33 |
| 07-03 Plot286 | 0.332 / 0.563 / 0.281 | 0.37 → 0.60 | 48/−17/+23 · 41/−15/+18 · 47/−21/+25 |

Stock library cowpea at calendar age covers about twice the real ground and is too tall (0.29–0.58 m);
the baseline's absolute numbers depend on the assumed planting date. The baseline JPEG is the
renderer's own and is in the label maps' frame (no flip; luminance correlation with the EXR 0.91–0.96).

### 4.9 Leaf-level observables and the leaf-shape fit (2026-09-14)

**Seed budget** (`scripts/twin_seed_budget.py`: stage 3 with a 64-seed pool, every candidate's IoU kept, expected best of K
read off exactly, then stage 4 from the best of 16 and of 64):

| frame | best-of-K per-plant IoU before refinement, K = 1 / 4 / 16 / 64 | after refinement, 16 → 64 seeds | scene IoU, 16 → 64 |
|---|---|---|---|
| 06-20 Plot286 | 0.352 / 0.385 / 0.410 / 0.429 | 0.441 → 0.453 | 0.470 → 0.481 |
| 06-27 Plot298 | 0.446 / 0.475 / 0.497 / 0.513 | 0.540 → 0.545 | 0.602 → 0.632 |

Each doubling of the pool adds about 0.005; 6 yaws instead of 12 cost about 0.007. Four times the stage-3 cost buys
0.005–0.012 per plant after refinement, so the pool stays at 16 seeds.

**Leaflet measures** (`twin/leaflets.py`, `scripts/twin_leaflets.py`): visible leaflet segments (largest piece, fitted
ellipse, solidity ≥ 0.8), from SAM on the photo and exactly from the raster's per-leaflet object map; and the thin-structure
fraction (share of vegetation removed by a 5 px opening at raster scale 0.5). SAM was checked where the truth is known: on the
rendered twins it matches the raster within a few per cent on 06-20 (27.7 vs 27.6 leaflets per plant, 36.4 vs 36.0 px long)
and within about 13 % on 07-03. On the photos (`twin_leaflet_panels.py`) the accepted masks are mostly single leaflets, but
SAM finds only about half of them, and the colour vegetation mask misses thin dark petioles; so length and width are targets
(SAM bias removed per frame), count is not, and the real thin fraction is divided by what the colour mask does to the twin's
(`scripts/twin_leaflet_targets.py`). The previous leaflet-aware fit was wrong in the direction its peak counter pushed it:

| frame | leaflet length × width px, real / twin | thin fraction, real (raster terms) / twin |
|---|---|---|
| 06-20 Plot286 | 62 × 35 / 36 × 17 | 0.047 / 0.145 |
| 06-27 Plot286 | 67 × 34 / 40 × 19 | 0.022 / 0.104 |
| 07-03 Plot286 | 71 × 40 / 43 × 21 | 0.019 / 0.088 |

**Leaf-shape fit** (`twin.stage1.LeafShapeObjective`, `scripts/twin_shape_opt.py`): the harness now exposes leaflet aspect
ratio, midrib fold, lateral and longitudinal curvature, leaflet offset and scale, petiole curvature and internode pitch
(applied only when given; the new binary reproduces the old bit for bit without them). Objective: best per-plant IoU minus
0.3 |log| length and width ratios and |thin fraction difference|, averaged over 06-20 and 06-27 Plot286; 250 TPE trials,
75 min on 8 cores. Best (trial 52): leaflet scale 0.116–0.124 m, aspect ratio 1.16, no midrib fold, petioles 2.5–4.4 cm
drooping, phyllochron 2.7 d, internodes 3.5 cm pitched 36°; the top ten agree on scale, aspect, fold, petiole length and
phyllochron. Refits of all five frames (Plot201, Plot298 and 07-03 held out), 16 seeds:

| frame | scene IoU | median per-plant IoU | leaflet px (target) | leaflets/plant |
|---|---|---|---|---|
| 06-20 Plot286 | 0.48 → 0.55 | 0.45 → 0.55 | 36×17 → 56×35 (62×35) | 28 → 9 |
| 06-20 Plot201 | 0.50 → 0.60 | 0.48 → 0.60 | 35×17 → 57×32 (53×31) | 27 → 11 |
| 06-27 Plot286 | 0.58 → 0.65 | 0.49 → 0.56 | 40×19 → 58×32 (67×34) | 42 → 18 |
| 06-27 Plot298 | 0.61 → 0.70 | 0.50 → 0.61 | 39×18 → 62×34 (48×28) | 44 → 16 |
| 07-03 Plot286 | 0.62 → 0.70 | 0.48 → 0.57 | 43×21 → 60×30 (71×40) | 58 → 24 |

The spokes are gone and the gain holds on the held-out frames. What the renders show next (`twin_work/report/shape/`):
leaflets are too round and angular (aspect ratio 1.16 stretches the leaflet texture: the measured width/length of *visible*
segments matches real, but occlusion shortens visible length, so the fit widened the prototype to compensate), leaves heap into
rosettes, the thin fraction now undershoots (0.006–0.016 against 0.02–0.05), Plot298's genotype has smaller leaflets than
Plot286's, and 07-03's leaves are larger than the June shape gives. Next: bound the aspect ratio to cowpea's range and score
leaflet shape only on unoccluded leaflets, and give leaflet size a growth term across dates.

**Rejected on inspection (2026-09-14, evening).** The leaf-shape twins' leaves are far too large and round; the
leaflet-aware fit looks much more like the plants. What misled the numbers: (1) SAM on the photos keeps 3–15 masks per plant,
misses most of the long pointed leaflets and sometimes returns a whole trifoliate leaf as one mask, so the real "leaflet size"
is a biased sample; the check on renders did not transfer (flat-shaded renders with clean edges segment easily). (2) The
twin side was a median over all visible pieces, young leaves and occlusion fragments included, so big overlapping leaves still
gave a median at the target. (3) Per-plant IoU with unmatched realisations rewards filling the footprint: broad overlapping
leaves raised scene IoU 0.07–0.10 (06-20 recall 0.68 → 0.77) while the plants got less realistic. The SAM-derived targets and
thin fractions above are not to be used; the leaflet-aware fit (`_leaf`) remains the reference twin. The seed-budget result
stands. Shape parameters need trustworthy leaf-level data (hand-measured leaflets) or must stay at the library values.

### 4.10 Spokes: leaf-angle bug, petiole colour, leaf count (2026-09-15)

The bare "spokes" in the leaflet-aware twins had three causes. (1) `PlantArchitecture::setPlantLeafElevationAngleDistribution()`
(harness `leaf.set_angle_distribution 1`) spun each leaf about its normal and flipped down-facing leaves, so blades turned by a
median 150 degrees about their bases and petioles stuck out past them; fixed in Helios (tilt only, rank-matched inclinations;
regression test in the plantarchitecture selfTest), median turn now 2.4 degrees. Every fit before this date used the buggy
function. (2) Stems used the colour checker's green patch (C* 62 against a real 36); now the leaf reflectance with 1 % yellow at
2x (`stem.yellow_fraction`, `stem.reflectance_scale`; `scripts/twin_stem_colour.py`), petiole minus leaf dL* +5.9 db* +6 against a
real +7.1 +5. (3) Too many small leaves on a compressed stem (phyllochron 0.96 d, 1.5 cm internodes, about 37 leaves per plant at
16 d), so 15+ petioles converge at each plant centre. Ground clipping was on but removed about one leaf per scene; now off by
default (`canopy.ground_clipping`).

Five-frame refits (`scripts/twin_spokes_compare.py`, sheets in `twin_work/report/diag/spokes_*.jpg`), scene IoU and the share of
visible vegetation that is stem or petiole:

| frame | old code (_leaf) | fixed code, library petioles (_fix) | fixed, fewer larger leaves (_fixD) |
|---|---|---|---|
| 06-20 Plot286 | 0.482, 0.085 | 0.510, 0.057 | 0.476, 0.030 |
| 06-20 Plot201 | 0.504, 0.078 | 0.557, 0.053 | 0.502, 0.031 |
| 06-27 Plot286 | 0.579, 0.056 | 0.599, 0.052 | 0.575, 0.024 |
| 06-27 Plot298 | 0.611, 0.061 | 0.651, 0.050 | 0.632, 0.026 |
| 07-03 Plot286 | 0.620, 0.054 | 0.620, 0.043 | 0.618, 0.024 |

_fix still shows pale petiole stars at plant centres; _fixD (phyllochron 2.7 d, internodes 3.5 cm, leaflet scale 0.09-0.12 m,
library petioles 6-8 cm, flatter leaf angles Beta(3, 1); `twin_work/fixD_overrides.json`) removes them at the old fit's IoU. IoU
again prefers the many-small-leaves plant, which looks wrong: leaf count per plant has to come from labels, not silhouettes.
_fixD is the interim reference twin until the labelled leaf count, leaflet size and petiole length are in.

**Scanned leaf meshes (2026-09-15).** The _fixD layouts rendered with `leaf.use_obj_mesh 1` (`twin_work/fixD_obj_overrides.json`,
into `<frame>_fixD_obj/`) give leaflet relief, venation and a broader outline, with no refit. Rasterized with the scanned leaves
the same layouts score higher on every frame (scene IoU 0.476/0.502/0.575/0.632/0.618 -> 0.495/0.529/0.587/0.655/0.624). Veins
at the default 15 % yellow read as bright yellow lines; 5 % (`leaf.vein_yellow_fraction 0.05`) matches the pale real veins. Cost:
1.6 min per render on an RTX A5500, about 10 s per scene raster instead of 1.5 s. Remaining: real leaves darker, glossier and
more savoyed than rendered (optics and specular, not geometry). Sheets: `twin_work/report/diag/obj_*.jpg`
(`scripts/twin_render_sheet.py`).

**Leaf colour refit (2026-09-15).** The per-frame chlorophyll had been fitted to the median foliage a*/b* on the _leaf renders,
where lime petioles (8 % of plant pixels, C* 59) supplied the saturated tail; with correct petioles and one Cab for every leaf the
foliage came out flat olive (06-20: C* p90 36 against a real 44). `scripts/twin_leaf_colour_fit.py` scores foliage L* p10/p90,
a*/b* p10/p50/p90, C* p90 (RMS vs real), one render per candidate. Random Cab per leaflet (`leaf.chlorophyll_sd` drawn per
leaflet) matched best (06-20 distance 4.8 -> 1.3) and was rejected by eye: leaflets of one petiole disagreed and whole leaves
turned abruptly yellow. Now per trifoliate leaf, shared by its leaflets: Cab = mature * (y + (1-y) min(1, age/8 d)) + N(0, 5), y =
`leaf.chlorophyll_young_fraction` 0.7, `leaf.chlorophyll_sd` 5 (per leaf), `leaf.chlorophyll_leaflet_sd` 0; Car/Cab 0.26,
Car/Cab 0.26. Specular is a normalized Blinn-Phong lobe (the (k+2)/2pi factor), so the scale sets the total specular energy and the
exponent only concentrates it: at the library exponent 35 the sheen washed over whole blades, at 250+ whole leaflets blew to white
(a leaflet is nearly flat), and exponent 100 with scale 0.035 puts it in narrow streaks along the midrib and the scanned mesh's
ridges. Mature Cab per frame and distance: 06-20 P286 62 (2.0), 06-20 P201 56.2 (3.4), 06-27 P286 59.8 (1.6), 06-27 P298 48.7 (2.9),
07-03 75.5 (1.3); median b* within 1-2 of real on every frame. Settings in
`twin_work/<frame>_fixD_obj/leaf_overrides_colourfit.txt`; renders `twin_work/colour/<frame>/H_*`. Remaining: within-leaf mottling,
and shadows lighter than real (P201 L* p10 34 against 31).

**Soil albedo level (2026-09-17).** Regenerating the four-pane figures on the best twin (_fixD geometry, scanned leaves, fitted
leaf colour; `scripts/twin_baseline_gallery.py --baseline render_current_sunoff --twin _soilfix --fit _fixD`) showed the soil ~10 L*
dark. Cause is the canopy, not the soil: at an exposure matched on soil the soil gain is unchanged from _leaf (707 vs 711) while
foliage goes L* 47 -> 55, i.e. the flatter, larger leaves are brighter. The leaf-colour fit cannot see this (it normalizes exposure
to foliage L50). `soil.reflectance_scale` does nothing when an albedo map is given (it scales the unused library spectrum); new key
`scene.soil_albedo_scale` multiplies the map, whose absolute level is itself the assumption `median_reflectance = 0.04` in
twin/soil.py. Fitted per frame: 1.66, 2.11, 1.84, 2.37, 1.68 -> soil L* within 2 of real on all five; foliage b* 2-3 units yellower
from the bounce, for the next chlorophyll refit. Renders in `twin_work/<frame>_soilfix/` (`scripts/twin_render_soilfix.sh`).
Baseline re-rendered with the current build as `baseline_<date>/render_current_sunoff`. Scene IoU baseline -> twin:
0.26->0.47, 0.23->0.51, 0.27->0.56, 0.35->0.63, 0.37->0.60.

**GPU note.** An interactive session on a bgpu node may have no GPU allocated (`nvidia-smi` shows none); Helios then falls back to
the Vulkan software backend and a 1.6 min render takes hours. Check first, and submit renders with sbatch to gpu-6000_ada-h.

### 4.11 Leaf size from hand labels, and what it costs the silhouette fit (2026-09-18)

Leaf size finally came from labels rather than from silhouettes. `twin_work/labels/label_tool.html` (published artifact) shows the
same crop rectangle of the same plant twice -- the real frame and the twin render, identical camera and colour chain, both at
0.783 mm/px -- and records four clicks per leaflet, two per petiole, and one per whole leaf for counting. Three crops of 06-20
Plot286 were labelled in both panes (45 real leaflets, 53 twin, 14 and 12 petioles):

| pooled, 3 crops | real | twin | twin/real | 95% CI | p |
|---|---|---|---|---|---|
| leaflet length | 53.8 mm | 61.8 mm | 1.15 | [0.99, 1.41] | 0.024 |
| leaflet width | 28.0 mm | 31.1 mm | 1.11 | [0.98, 1.23] | 0.049 |
| petiole length | 82.2 mm | 58.2 mm | 0.71 | [0.60, 0.84] | <0.001 |

Leaflet shape is right (W/L 0.52 real, 0.50 twin), so the leaf-shape refit stays retired. The architectural error is the stalk:
petiole/leaflet length is 1.53 in the real plants and 0.94 in the twin. Counting in one crop gave 225 real against 194 twin
leaves/m2 -- areal density only, since a crop spans three twin plants aged 10.7 to 20.4 d plus parts of several real ones -- while
projected foliage cover came out 0.75 against 0.77 m2/m2. The twin reaches the right cover with short stalks and oversized leaves,
which is the degeneracy silhouette IoU cannot break.

**The automated leaflet measurement reads short in dense canopies.** `twin.leaflets.synthetic_leaflets` measures connected
components of *visible* leaf pixels, keeps the largest piece and drops anything below 0.80 solidity, so an occluded leaflet is
measured clipped or not at all -- and the denser the canopy, the shorter it reads. It put this twin at 46 mm where hand labels of
the same render measure 61.8. Every leaf-size conclusion drawn that way was biased against the twin, including the comments in
`main.cpp` (leaf scale, leaf inclination) asserting synthetic leaves measure ~19 % smaller than real; the reverse is true.

**The ruler** (`main.cpp diag.leafruler`, `scripts/twin_ruler.py`) replaces it: every leaflet is written as the four world points a
label clicks -- base, farthest vertex along the midrib, and the widest cross-section either side of it -- and projected through the
camera, so an occluded leaflet still measures its full length. Two traps: with `leaf.use_obj_mesh 0` the leaf is a texture-masked
quad whose farthest vertex is a corner off the blade (run the ruler with the scanned meshes, as the renders do), and the raster
object map numbers organs in rasterization order, so the binary now writes `<base>_objindex.txt` beside the maps to join a Helios
object ID to its pixels. Sampled as a labeller does -- the four largest at-least-half-visible leaflets per plant -- it reproduces
the hand labels on the same render: 62.7 mm against 61.8. Width does not: 37.7 against 31.1, so the ruler is validated for length
only.

**Correcting the two parameters costs silhouette IoU.** `leaf.prototype_scale` 0.090-0.120 -> 0.078-0.104 m and
`leaf.petiole_length` 0.060-0.080 -> 0.085-0.113 m (the measured ratios; projected size scales linearly with them at fixed
angles). Rendered separately on the fitted 06-20 layout (`scripts/twin_size_test.sh`, `scripts/twin_size_compare.py`), cover in the
labelled crops goes real 28.4 %, current 29.2 %, petiole only 31.7 %, leaf size only 23.9 %, both 25.7 %: the petiole correction
does the visible work, removing the rosette clumping, and the pair opens a 2.7-point cover deficit. Refitting ages and positions
with both pinned (`scripts/twin_refit_many_cpu.sh`, `_size`) lowers scene IoU on every frame -- 0.476->0.396, 0.502->0.432,
0.575->0.524, 0.632->0.544, 0.618->0.602 -- while fit ages rise only 0.5-1.5 d and stay far from the table ceiling, and cover falls
short of real on the dense frames (0.234 real vs 0.202; 0.335 vs 0.279). At a matched footprint the corrected canopy is too
sparse: with leaf size pinned by labels, leaf *number* is the only parameter left, which is what the eye said from the start.
`scripts/twin_phyllochron_sweep.sh` tests that directly.


**Bare stalks are architecture, not missing leaves (2026-09-18).** The refit's exposed petioles were checked organ by organ
(`diag.petiolecensus`, `diag.stalkdump`, `raster.split_stems`): of 215 phytomer petioles across 16 plants, none is bare, none
is missing part of its leaflets, there are no pruned shoots, no orphaned petiole objects and no peduncles, and every leaflet
touches its own stalk (closest approach median 0.1 mm, max 0.5 mm). In the image, all 112 petioles with a visible stalk show
thousands of pixels of their own leaflets (median 2845). A mature petiole is ~94 mm and carries its leaflets only at the tip,
so two-thirds of every stalk is bare by construction; lengthening petioles 1.41x while shrinking blades 13 % exposed more of
it against soil. Two defects surfaced on the way, both fixed. `output.write_leaf_ids 1` wrote an all-zero map for any run whose leaves
took one uniform spectrum, because the leaf-ID assignment sat inside the nitrogen-driven spectrum branch; it now runs
wherever the map is asked for, and an empty map is a `helios_runtime_error` rather than a silent zero file (checked by
`scripts/twin_leafid_check.sh`, which renders the configuration that used to fail: 590 IDs assigned, 501 distinct in the
map). `scripts/twin_refit_many_cpu.sh` also carried appearance over from `_leaf`, the first uniform-colour fit, so the
`_size` refit was rendered with different leaf optics from the twin it was being compared against; it now takes them from
`_soilfix`. And the leaf
angle distribution draws from the Context's global generator, so its poses depended on whatever drew from it earlier
(`leaf.angle_seed` now fixes the draw). A reported raster-vs-render canopy divergence was a comparison error of mine: the
render script passes `canopy.per_plant_seed 1` explicitly while the render `ov.json` omits it and `baseline.cfg` leaves it 0,
so an ad-hoc rasterization of the same ov.json builds a different canopy (581 leaves against 590). Given identical arguments
the two modes agree exactly -- every leaf base and tip matches to 0.000 mm (`scripts/twin_ruler.py`, diag.leafruler dumps).

### 4.12 The yaw rotation tore every plant apart (2026-09-18)

The bare stalks were a real defect, and not the one the census first said. Per-plant yaw is applied after growth
(`main.cpp`, the loop over sites) and was applied as `Context::rotatePrimitive()` over `getAllPlantUUIDs()`. That call
transforms each primitive it is handed, which moves a leaf -- a patch or a polymesh -- but does nothing whatever to a
petiole or an internode, because those are tube objects and `Primitive::applyTransform()` refuses to transform a
primitive belonging to a compound object. Helios does say so ("WARNING (Primitive::applyTransform): Cannot transform
individual primitives within a compound object"), but that warning goes to stdout, and every caller in this project
filters the binary's output down to its DIAG lines, so no one ever saw it. The UUIDs are all present in the list
(coverage checked at 100 %). So every plant with a non-zero yaw had its leaves swung round its base while every stalk
stayed where it was.

Measured on the 06-20 Plot286 layout, by dumping leaf and petiole geometry before and after the rotation
(`diag.leafruler`, `diag.stalkdump`, `diag.yawcoverage`): leaves rotate by exactly the site yaw (90 deg -> 90.0, 110 ->
110.0, 270 -> -90.8), petioles rotate by 0.0 deg. The distance from each petiole to the leaflets it carries, which is
0.1 mm before the rotation, becomes a median of 20 mm and a maximum of 99 mm after it, and the two plants in the scene
whose yaw is near zero (+10 and -10 deg) are the only ones left intact (median gap 1.3 and 0.2 mm). Rotating the plant's
*objects* instead (`Context::rotateObject()` over `getAllPlantObjectIDs()`, with loose primitives still handled by the
primitive call) restores it: median gap 0.08 mm, max 0.8 mm, none above 5 mm.

Two things this invalidates and one it does not. Every fit since per-plant yaw was introduced scored a torn canopy, so
fitted positions, ages and yaws, and every cover and IoU number derived from them, need redoing. The hand-labelled leaf
measurements survive: the rotation is rigid and about the vertical axis, so leaflet and petiole lengths, and their
projections into a nadir view, are unchanged by it -- leaflets 15 % too long and petioles 29 % too short still stand.

The guard against it: one petiole vertex per plant is checked across the rotation against where the rotation should
have put it, and a mismatch above 1 mm is a `helios_runtime_error` naming the tube-object cause. Verified by restoring
the broken call: the guard fires on plant 0 with the probe 4.4 mm out of place, and passes at 3e-5 mm once fixed. The
second lesson is about log filtering -- the pipelines here keep only DIAG lines, which threw away the one warning that
would have named this bug on its first run.

A trap worth remembering: a diagnostic that walks the plant structure sees the intact plant if it runs before the
rotation and the torn one if it runs after. The first census ran before it and reported every petiole perfectly leafed,
which is how this was missed the first time. The diagnostics now sit after the rotation, where they describe the geometry
that is actually drawn.


**Refit and re-render with the rotation fixed (`_yawfix`, 2026-09-18).** Five frames refitted in 9 min and rendered in
6 min, leaf scale and petiole length still pinned to the hand labels. Scene IoU barely moves (0.396->0.398, 0.432->0.439,
0.524->0.508, 0.544->0.541, 0.602->0.596): a rigid rotation of the leaves about the plant base leaves a
similarly-shaped silhouette, which is why the metric was nearly blind to plants being torn in half and why this survived
as long as it did. Cover is the informative one, and it now has a clean structure -- the two young sparse frames match
real to about 1 % (+0.4 %, -1.2 %) while the deficit grows with canopy age: -10.3 %, -10.0 %, -16.5 %. Fit ages hardly
moved (13.8->13.4, 25.0->25.0), so the fit is not absorbing it. A shortfall that compounds with development is a leaf
*production* shortfall -- phyllochron and branching -- not a per-leaf error, and with leaf size pinned by labels there is
nothing else left for it to be.

### 4.13 Emergence, not leaf production (2026-09-18, evening)

Pinning plant age to a date outside the fit looked at first like it had exposed a broken growth trajectory: with
emergence at 2023-06-08, the phyllochron needed to match cover came out 1.5 d/node at 12 days, about 2.4 at 19 and 2.0 at
25, which is not a parameter value but a curve of the wrong shape. It was an artifact of the pinned date.
`scripts/twin_growth_curve.py` walks the model's cover-against-age curve at nine ages for each phyllochron, on each
frame's own fitted layout, and then finds the single (emergence, phyllochron) pair that passes through all three
Plot286-MAGIC083 dates at once. It lands on **emergence 2023-06-06 with phyllochron 2.7 d/node** -- the value already in
use -- for an rms cover error of 5.6 % (-4.0 %, -2.0 %, -8.6 % at 14, 21 and 27 days).

Two days of emergence were carrying the whole apparent deficit. Cover roughly doubles every 5-7 days at this stage, so a
two-day error in emergence is a 25-30 % error in cover, worst at the youngest frame where the relative slope is
steepest -- which is exactly the size and the pattern of the shortfall that had been attributed to leaf production
through three sweeps. Leaf number, phyllochron and branching are all defensible as they stand once leaf size comes from
the labels; what was wrong was a date.

The lesson for the fitting structure: per-frame fits cannot separate when a stand emerged from how fast it accumulates
leaf, because a plant matches the same outline younger if it makes leaves faster, and every sweep that leaves both free
will trade one against the other. A genotype's own time series settles it in one fit. Two cautions remain -- 2.7 is the
slowest phyllochron tested, so the optimum sits on a grid edge again (the -8.6 % residual at the oldest date leans that
way), and the curve fit reuses fitted plant positions, so it tests the trajectory and not the layout.

### 4.14 Why the footprints do not overlap: capacity, not search (2026-09-21)

Per-plant silhouette IoU sits at a median of 0.416 over the 81 fitted plants, and the obvious question -- optimize
harder, or is something missing from the model -- has opposite answers with opposite costs, so
`scripts/twin_footprint_diagnostics.py` measures which. Run on 06-27 Plot298 with the leaf angles the model generates
natively (the Beta(3,1) re-aim dropped, see below), three results:

**Masks are sound.** 19 plants, area median 11081 px, the largest 2.7x the median: no merged pairs, no fragments. The
segmentation is not what caps IoU.

**Search is exhausted.** Best-of-N IoU against N realizations of the same plant, position and age held:

| plant | area px | N=16 | N=64 | N=256 | N=1024 | the fit |
|---|---|---|---|---|---|---|
| 6 | 30436 | 0.502 | 0.513 | 0.524 | 0.540 | 0.554 |
| 13 | 19628 | 0.474 | 0.499 | 0.499 | 0.499 | 0.527 |
| 16 | 19333 | 0.407 | 0.407 | 0.413 | 0.416 | 0.434 |
| 7 | 18946 | 0.462 | 0.462 | 0.462 | 0.498 | 0.492 |

Sixty-four times the seeds buys between 0.009 and 0.038, and two of the four curves are flat across most of that range.
The realizations are not there to be found; more compute against the same generator will not produce them.

**The headroom is real.** Matching each real plant against other real plants of comparable footprint, best over 90-degree
rotations and mirroring, gives a median IoU of 0.629 (p90 0.729) -- what a correct cowpea that is not this individual
achieves, and a conservative estimate since rotation is coarse. The fit reaches 66 % of that, leaving about 0.2 of IoU
that is model-side rather than identity.

So the next move is architecture, not optimization: `canopy.insertion_angle_tip`, `canopy.insertion_angle_decay`,
`canopy.internode_length_decay`, `canopy.gravitropic_curvature`, `canopy.tortuosity`, `canopy.phyllotactic_angle`,
`leaf.petiole_flexibility`, `leaf.petiole_curvature`, `canopy.leaf_expansion_rate` and `canopy.elongation_rate` are now
exposed, none of which had ever been fitted. They belong to the stand, not to a plant, so they should be fitted once
against the distribution of shape descriptors and cover rather than per-plant IoU -- which rewards foliage wherever it
lands, as three sweeps showed. Per-plant IoU keeps its proper job: placing a plant whose architecture is already right.
Re-running the seed curve afterwards says whether the saturation level moves from 0.50 toward 0.63.

One-at-a-time sensitivity on 06-27 Plot298, against the library defaults (cover 0.172, canopy top 0.314 m), so that the
fit searches dimensions that actually move the footprint:

| knob | range tried | cover | |
|---|---|---|---|
| `leaf.petiole_flexibility` | 0 -> 8000 | 0.172 -> 0.072 | very strong; 8000 is an extreme probe, a usable range still has to be found |
| `canopy.insertion_angle_tip` | 25 -> 70 | 0.153 -> 0.180 | strong, about 8 % either side of the default |
| `canopy.gravitropic_curvature` | 0 -> 1000 | 0.167 -> 0.171 | weak: 2.4 % across the whole range |
| `canopy.tortuosity` | 40 | 0.170 | weak: -1.3 % |
| `canopy.phyllotactic_angle` | 75 | 0.171 | no effect on cover, -8 % canopy height |

Two knobs carry the footprint and three barely move it, which is what one would expect of a plant whose spread comes
from 94 mm petioles rather than from stem curvature: these shoots are about 45 cm of 3.5 cm internodes, so bending them
does little. Phyllotactic angle is worth keeping as a shape-only dimension, since it moves canopy height without moving
cover and may change silhouette form where cover cannot see it. The inert ones are not a plumbing fault -- the harness
writes the `trifoliate` shoot type, and cowpea's only other type is `unifoliate`, a one-node seedling shoot carrying
almost no canopy.

**Leaf angles, while measuring this.** Measured cowpea runs Beta(1.398, 1.574) -- mean inclination 42.3 degrees --
consistently across many genotypes (B. Bailey). The harness had been imposing Beta(3, 1) on finished plants, which
flattened the canopy to 32.1 degrees and inflated projected footprint; the model's own leaf angles give 44.0 degrees,
within two degrees of the measurement, so that setting was removed. `PlantArchitecture::enablePlantLeafElevation-
AngleDistributionTracking()` (new in 1.3.87, exposed as `leaf.angle_tracking`) steers angles through growth rather than
re-aiming a finished plant, but toward this target it moves the canopy the wrong way as
`getPlantLeafInclinationAngleDistribution()` reports it: L1 distance to the target rises from 0.235 to 0.251, with leaf
area piling into the steepest bins (70-90 degrees: 0.109 -> 0.248 against a target of 0.139) monotonically in lambda.
Helios's own selfTest asserts the opposite, but it measures one inclination per leaf object on rigid blades
(`leaf.prototype.flexibility = 0`, species bean) while the public getter accumulates blade facets -- a curved or
drooping blade contributes a spread of facet inclinations. Left off pending an answer from the Helios side.

### 4.15 There was no visibility bias; the leaflet correction is the one that did not land (2026-09-21)

The petiole and leaflet size corrections (x1.41 and x0.87, section 4.11) came from hand labels, so the worry was that
they compared a labeller's *visible* organs against the twin's *whole population*: the labeller cannot measure a
half-expanded petiole buried in the canopy centre, the population median includes it, and the correction then inherits
that gap. A raster measurement seemed to confirm it, putting visible petioles at 1.63x the population median.

That 1.63x was wrong twice over. The visible-pixel counts came from the half-resolution raster while the silhouette
areas they were divided by were computed in full-resolution camera pixels, so every visibility fraction was 4x too
small -- "20% visible" was really 80% visible, and asking for 40% asked for 160%, which is why that bucket returned
eleven absurd leaflets with a 5 mm median. And 58 of the 406 "petioles" in the stalk dump are petiolule stubs under
5 mm, which drag the population median down on their own. With consistent units, the stubs dropped, and visibility
measured as *axis traceability* -- the share of samples along base-to-tip whose pixel in the object map belongs to
that organ, which is what a labeller needs to place a line, where visible area is not (a leaflet can show 60% of its
area with its tip buried) -- the ratio is 1.0x for petioles and 1.25x for leaflets. There is no large bias.

More to the point, the premise was unnecessary: the corrections never compared labels against a population. The
labelling tool has two panes, and the same eye measured the same way on both. Real against twin, 45 and 53 leaflets
over three plants of 2023-06-20 Plot286: leaflet length 53.8 against 61.8 mm (x0.87), petiole 82.2 against 58.2 mm
(x1.41). That is already visible-to-visible, and it stands.

What the geometry ruler does settle is whether the corrections landed. Measured in the three labelled crop boxes on
the current `_final` fit, ranking organs by visible pixels and taking as many as the labeller took:

| | real labels | twin, 18 Sep (labelled) | twin, current |
|---|---|---|---|
| leaflet length | 53.8 mm | 61.8 | ~74 |
| petiole length | 82.2 mm | 58.2 | ~85 |
| leaflet / petiole | 0.65 | 1.06 | 0.87 |

The petiole correction landed -- petioles now match the photograph crop by crop (94.9/85.4/80.0 against 88.0/77.1/79.8).
The leaflet shrink did not: applying x0.87 and x1.41 should have taken the within-plant ratio from 1.06 to 0.65, and it
went to 0.87. Leaflets are about 1.35x too large relative to their own petioles, which says shrink `leaf.prototype_scale`
by a further ~0.75x, to roughly 59-78 mm.

Two things to hold on to. The ratio is the trustworthy number, because it is scale-free: the absolute twin medians
swing by 1.8x depending on which leaflets are counted as the ones a person would measure (35-50 mm taking every
leaflet with the axis >=70% in view, 69-76 mm taking the most conspicuous N), and the real labels sit between. The
ratio cancels that. Second, a 0.75x shrink costs 0.55x of leaf area, so the refit will buy the cover back with leaves
-- more, smaller leaves on longer petioles, which is the direction the radial profile and the solidity deficit
(0.59-0.66 against 0.81) have been pointing all along. The twin pane of the labelling tool now shows the current
render, with the September labels kept under their own key, so the next round of labels tests all of this directly.

**Superseded by 4.16**: the 0.75x recommendation above is an artifact of the top-N estimator and should not be applied.

### 4.16 The ring, measured on the geometry: leaflet shape, not leaflet size (2026-09-21)

BB, from the renders: "lots of long petioles with distal leaves and relatively little in the middle ... some
combination of lack of lateral branching, and petioles elongating too fast ... the fully elongated petiole lengths
look about right, maybe a hair too long ... the real petioles look like they have some curvature to them whereas the
generated ones look stick straight." Measured on the built geometry, where neighbouring plants cannot blur the
answer, the ring is real and none of the aggregates had been able to see it.

**The ring.** Blade area by distance from its own plant's stem: 10.8% of it lies within 50 mm, 79% between 50 and
125 mm, 1.2% beyond 150. A uniform disc of the same extent would put 11% inside 50 mm and 31% beyond 125. Against
the photograph, radial density per plant (1.0 = uniform disc) is flatter in the twin through the outer half --
0.95 / 0.83 / 0.50 at r/r95 of 0.6-0.7, 0.7-0.8, 0.8-0.9 against the real 0.83 / 0.59 / 0.40. The whole-plant
profile hides it: the twin's inner third reads 1.41 against the real 1.38, but counting blade pixels alone it is
1.22. **The twin's middle is filled by petioles, not by leaves**, which is exactly what the eye reported and what
every mask-level aggregate had been scoring as a match.

**What is not causing it.** Branching is present: 4 shoots per plant, 57-60% of nodes on branches. And the
petiole does not outrun its blade -- at leaf_scale 0.3 / 0.5 / 0.7 / 0.9 the petiole stands at 25 / 41 / 61 / 83%
of its own maximum, near lockstep.

**What is: the blade does not outrun the petiole either, and it must.** Lockstep was tested as though it were the
answer, and it is not; it is only the absence of the failure that was being looked for. Under one rate a node at
half expansion sits at half the petiole's reach carrying a quarter of its blade area, because area goes as the
square of the scale -- a small leaf already pushed outward, which is the hole. BB, from the tomato fit: the leaves
expand first and the petiole follows, and tying the petiole to the internode while giving the blade its own rate
"fills up space in the hole, while still allowing the fully-elongated petiole/leaflets to fill up the footprint."

`ShootParameters::leaf_expansion_rate_max` exists for exactly this and **no species in PlantLibrary.cpp sets it**,
so every library plant runs one rate. Blade-pixel radial density per plant against the photograph, over the split
(1.0 = uniform disc, r/r95 in tenths):

| | 0.0 | 0.1 | 0.2 | 0.3 | 0.4 | 0.5 | 0.6 | 0.7 | 0.8 | 0.9 | L1 | cover |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| real | 1.36 | 1.40 | 1.39 | 1.33 | 1.16 | 1.03 | 0.83 | 0.59 | 0.40 | 0.26 | -- | -- |
| library, one rate | 1.58 | 1.78 | 1.28 | 1.07 | 1.04 | 0.91 | 0.77 | 0.69 | 0.47 | 0.23 | 1.47 | 0.076 |
| leaf 0.20 | 1.58 | 1.73 | 1.31 | 1.22 | 1.20 | 1.01 | 0.70 | 0.61 | 0.39 | 0.26 | 0.96 | 0.116 |
| leaf 0.50, petiole 0.05 | 1.54 | 1.54 | 1.41 | 1.34 | 1.28 | 1.02 | 0.76 | 0.58 | 0.41 | 0.21 | **0.62** | 0.107 |

The one-rate twin has a spike of tiny blades at the apex, a deficit through the middle and a fat rim -- the ring.
Decoupling cuts the distance to the photograph by 58%, and improves the mid-band (0.49 -> 0.15) and the rim (0.26
-> 0.14) together. Raising the blade rate alone fills the middle but leaves the rim heavy; slowing the petiole is
what thins it. Cover rises too, and these fits are short of cover. Note that `canopy.elongation_rate` drives the
internode as well -- that is the design, the petiole elongating on the shoot's internode rate -- so slowing the
petiole slows the internode with it.

**Organ sizes were right all along.** The 1.23x leaflet claim above came from defining maturity as leaf_scale >=
0.95, a criterion the rate under test moves: a fast blade rate makes more nodes qualify and the measured sizes
drift with it (66 -> 82 mm across the sweep). Taken with no maturity criterion at all, the twin's p90 blade is
1.02x the real p90 and the mature petiole 1.05x the labelled one. BB judged both right from the renders and was
right.

What does survive is blade *shape*: width/length 0.421 against the real 0.523, unchanged in the largest quartile,
so about 1.24x too slender. That is worth fixing on its own account but cannot fill the hole -- it only
redistributes area within the rim.

**Two levers withdrawn.** Internode length: the 0.54 m "measured" plant height is a hardcoded constant in
main.cpp with no provenance in this repository, and these are nadir views, which see in-plane extent and not
height. Petiole curvature: the rods are real (2.1% sagitta, arc/chord 1.002) but bowing them pulls the canopy in,
which risks the outer footprint that currently matches.

### 4.17 The rate split, refitted over all five frames (2026-09-21)

`canopy.leaf_expansion_rate 0.5` against `canopy.elongation_rate 0.05`, everything else as `_final`, refitted
(`scripts/twin_rate_refit.sh`, `twin_work/rate_refit_ov.json`) and compared with `scripts/twin_rate_compare.py`.

| frame | IoU _final | IoU _rate | recall | blade profile L1 | cover real / _final / _rate |
|---|---|---|---|---|---|
| 06-20 Plot286 | 0.369 | **0.441** | 0.56 -> 0.74 | 1.46 -> **0.60** | .089 / .095 / .126 |
| 06-20 Plot201 | 0.407 | **0.566** | 0.60 -> 0.78 | 1.45 -> **0.85** | .096 / .102 / .112 |
| 06-27 Plot286 | 0.477 | **0.544** | 0.63 -> 0.71 | 2.44 -> **1.44** | .182 / .172 / .182 |
| 06-27 Plot298 | 0.546 | **0.677** | 0.72 -> 0.84 | 1.30 -> 1.60 | .234 / .245 / .253 |
| 07-03 Plot286 | 0.593 | **0.622** | 0.73 -> 0.76 | 3.06 -> 2.83 | .335 / .323 / .331 |
| mean | 0.478 | **0.570** | | 1.94 -> 1.46 | \|err\| 0.90% -> 1.52% |

Silhouette IoU rises on every frame, by 0.092 on average. It rises through recall -- 06-20 Plot286 goes from
0.56 to 0.74 at unchanged precision (0.521 -> 0.522) -- which is the specific claim being tested: the added area
lands on real plant pixels rather than spilling outside the plant. The blade radial profile improves on four
frames of five.

Two costs, and they are the same cost seen twice. A petiole at 0.05/day needs twenty days to finish, and these
plants are 14 to 27 days old, so the mature petiole now reads 68-76 mm against the 82.2 mm hand label where
`_final` read 84-87. And cover overshoots on the youngest frames (.126 against .089 at 06-20 Plot286), where a
blade finishing in two days puts full-size leaves on a plant that has not earned them. Both say 0.05 is too slow
for the petiole rather than that the split is wrong: the next step is a milder one (petiole 0.07) with
`leaf.petiole_length_max` raised enough that a petiole still reaches the labelled length by imaging time.

**What the renders show, which the IoU hides.** On the open young frames the change is unmistakable and in the
right direction: the one-rate plants are visibly spoked, long bare petioles with a blade on the end and gaps
between, and the split gives filled rosettes much closer to the photograph. On the closing and closed frames it
overshoots -- the canopy becomes a mat of uniformly large blades and loses the size gradient and the visible stem
structure the photograph has, to the point that one-rate is arguably the closer texture at 06-27 Plot298. That is
the same 0.5/day seen a third way: a blade finishing in two days leaves a plant with almost no range of leaf
sizes, where a real canopy grades continuously. The blade rate wants to be fast enough to outrun the petiole and
no faster -- 0.20 against a petiole 0.07, with `leaf.petiole_length_max` raised so a petiole still reaches the
labelled 82 mm by imaging time. In the single-frame sweep leaf 0.20 alone already took L1 from 1.47 to 0.96 with
the best rim match of the blade-only variants.

The two frames where the profile does not improve are the closed ones, where the real per-plant labels merge
neighbouring plants and the real profile itself is least trustworthy -- 07-03 reads 1.88 at the stem falling to
0.28, far more centre-heavy than any of the open frames.

### 4.18 The rate split, second iteration: 0.30 / 0.05 with the petiole length compensated (2026-09-21)

0.5/0.05 filled the middle but flattened the canopy into a mat of uniformly large blades and left the mature
petiole 12% short. A grid over blade rate x petiole rate, scored on two frames at once -- an open one and a
closing one, because they disagree -- picked the only setting near-best on both:

| blade / petiole | 06-20 L1 | 06-27 L1 | sum | blade p75/p25 |
|---|---|---|---|---|
| library, one rate | 1.46 | 1.30 | 2.76 | 4.20 / 3.06 |
| 0.20 / 0.10 | 0.97 | 2.78 | 3.75 | 2.70 / 1.96 |
| 0.30 / 0.05 | 0.89 | 0.66 | **1.55** | 2.11 / 1.79 |
| 0.50 / 0.05 | 0.62 | 1.38 | 2.00 | 1.77 / 1.47 |

A slow blade (0.20) scores well on the open frame and badly on the closing one; a fast blade does the reverse and
collapses the leaf-size spread. 0.30 keeps both.

**Part of that gain was not the rate split.** At 0.05/day a petiole needs twenty days and these plants are
fourteen to twenty-seven, so it never reaches the length it was given -- and short petioles improve a radial
profile for a reason that has nothing to do with the mechanism under test. Raising `leaf.petiole_length` by 1.145
puts the mature petiole back on the hand label and costs some of the score, which is the honest number:

| | 06-20 | 06-20 P201 | 06-27 P286 | 06-27 P298 | 07-03 | mean | mature petiole |
|---|---|---|---|---|---|---|---|
| `_final` L1 | 1.46 | 1.45 | 2.44 | 1.30 | 3.06 | 1.94 | 86.3 / 72.6 / 87.0 / 84.7 / 87.5 |
| `_rate` (0.5/0.05) | 0.60 | 0.85 | 1.44 | 1.60 | 2.83 | 1.46 | 71.8 / 72.7 / 68.2 / 69.5 / 76.3 |
| `_rate2` (0.3/0.05 x1.145) | **0.40** | **0.67** | 1.54 | 1.43 | 3.21 | **1.45** | **82.2 / 82.5** / 73.7 / 72.9 / 85.9 |

On the two frames that carry hand labels the mature petiole now reads 82.2 and 82.5 mm against a labelled 82.2.
Scene IoU is 0.566 against `_rate`'s 0.570 and `_final`'s 0.478, at the best precision of the three (0.692
against 0.689 and 0.639) -- the same silhouette agreement as `_rate`, reached with slightly less spill, and a
large gain on `_final`.

**The renders agree, which is what decided it.** On the open frame 0.3/0.05 shows stem structure between the
leaflets again -- the thing 0.5/0.05 had flattened away -- on filled rosettes rather than spokes, and with a
visible range of leaf sizes; it is the closest of the three to the photograph. On the closing frame it recovers
most of what 0.5/0.05 lost, petioles and small leaves legible again, while keeping the density that the one-rate
canopy lacked. On the closed frame it gives a continuous row band where one-rate is visibly gappy. The blade
p75/p25 of 2.11 / 1.79 against 0.5/0.05's 1.77 / 1.47 is the same fact in a number, and it is why 0.30 was taken
over the 0.40 and 0.50 settings that scored better on the open frame alone.

07-03 remains the outlier for all three: its real profile is 1.88 at the stem falling to 0.28, far more
centre-heavy than any open frame, which is what a per-plant label looks like when the canopy has closed and
neighbouring plants merge into one another. It is the least trustworthy target in the set, and no setting
reproduces it.

## 5. Goal restated, and the plan for it (2026-09-11, afternoon)

The purpose is **calibration of the plant model against the field: take a picture, get a
Helios model.** The deliverable is therefore a parameter set for the plant model (shoot
parameters, phenology and growth rate, leaf angle distribution, leaf optical properties) plus
the scene that reproduces the picture (layout, ages), with the uncertainty on each parameter.
The realisation search and the render are checks, not the product. That ordering sets the
plan:

1. **Identifiability before more fitting.** Simulation-based check (`scripts/twin_identifiability.py`):
   a synthetic target with known parameters (real layout, fresh seeds) goes through the same
   optimiser; recovery per parameter is measured as the spread and bias of the top trials in
   units of the search range. Run with the optimiser's winner and with a random truth. This
   says which parameters a nadir silhouette can pin at the seedling stage and which cannot be
   claimed from it, whatever a real fit returns.
2. **Richer observables.** Leaflet masks (size, count, orientation, elongation) on the sparse
   frames, and the eight-date series of the same plot for growth rate and phenology. Silhouettes
   identify compactness (petiole and internode length) and nothing else; angles, pitch spread,
   phyllochron and flowering need these.
3. **Phenology as a fitted curve**, not inherited: one model-day to calendar-day rate and the
   flowering threshold across the dates of a plot, with per-plant ages tied to it.
4. **The output format.** A Helios-consumable calibrated model: the flat config the harness
   already reads (`scripts/twin_export_model.py` writes it from a fit and an optimiser result),
   and the same values as a PlantArchitecture library entry. Report a band of accepted parameter
   sets, not one point.
5. **More of the model's parameters in the search** where the picture can see them: leaflet
   scale and aspect, leaf flexibility (droop), branching probability, internode radius.
6. **Closed canopy through the time series**: positions inherited from the June frames of the
   same plot, so only realisation and appearance remain; the pure single-image closed-canopy
   case stays a research question.
7. **Upstream Helios changes** once justified: per-plant shoot parameters (so plants in one
   scene can differ in shape, needed for genotype and plot variation) and per-phytomer random
   addressing (so one leaf can be redrawn without regrowing the plant).
8. **Appearance stays a check**, with two exceptions that are themselves model calibration:
   leaf optical properties from foliage colour (PROSPECT pigments through the calibrated
   chain), and the real soil as the ground albedo so that the check is not dominated by a flat
   tile.
