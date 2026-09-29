# Fitting Helios PlantArchitecture to real data — notes for the next agent

Written 2026-09-07, from the Syn2Real cowpea project (`projects/SyntheticAutotuning/`), whose goal
was to generate synthetic imagery good enough to train a flower detector that transfers to real
field images. The next project is different — fitting the architecture model to **Pheno4D 3D scans
of individual plants**, matching one plant rather than tuning a distribution — but the model, the
library and most of the traps are the same.

Read §1 and §2 before touching parameters. §3 is the methodology that cost the most time to learn.

---

## 1. Things about PlantArchitecture that are not obvious and will cost you a day each

### 1.1 A "leaf" in the API is a compound leaf, not a leaflet

`getPlantLeafObjectIDs()` returns **compound leaves**. For cowpea that is a petiole plus three
leaflets, and its bounding box spans the whole assembly — we measured a median box major axis of
391 tile-pixels (~344 mm) where an individual leaflet is nearer 60 px.

This matters enormously for 3D fitting. Scan segmentation almost certainly gives you **leaflets**
(that is what a human labels, and what SAM returns). If you match scan leaflets against API leaf
objects you will be comparing objects that differ by a factor of three in linear size and by
`leaves_per_petiole` in count. Decide the correspondence explicitly and write it down.

Relevant: `phytomer_parameters.leaf.leaves_per_petiole` (3 for cowpea),
`leaflet_scale` (0.9 — successive leaflets shrink), `leaflet_offset`.

### 1.2 `getPlantHeight()` includes peduncles, not just the stem

We measured "plant height" at 0.633 m against a field-measured 0.54 and briefly treated it as a stem
defect. It is not: peduncles are 0.36–0.41 m in this configuration and stand above the canopy, and
changing *flower* parameters alone moved the reported height from 0.571 to 0.706. If you are fitting
to scans, compute height from the geometry you actually care about rather than this call.

### 1.3 Shoot parameters are reachable, but only through a copy-modify-write cycle

There is **no** per-plant setter for internode length, phyllochron or node count. What works:

```cpp
ShootParameters sp = plantarchitecture.getCurrentShootParameters("trifoliate");
sp.internode_length_max = ...;
sp.phyllochron_min      = ...;
sp.max_nodes            = ...;
sp.phytomer_parameters.leaf.prototype_scale.uniformDistribution(lo, hi);
plantarchitecture.updateCurrentShootParameters("trifoliate", sp);
```

This is global to the shoot type, not per plant — a real limitation if you fit plants individually.
Per-plant setters that *do* exist: `setPlantPhenologicalThresholds`, `setPlantLeafAngleDistribution`,
`setPlantLeafElevationAngleDistribution`, `setPlantMaxAge`, `setPlantBasePosition`,
`setPlantNitrogenParameters`, `setPlantCarbohydrateModelParameters`, `setPlantAttractionPoints`.

**If you need per-plant architecture, you will have to add it.** For fitting individual scans that is
likely the first thing you need, and it is a strong candidate for an upstream contribution.

### 1.4 The cowpea library's internode spacing is too tight, and this is the big one

```
internode_length_max = 0.025 m     phyllochron_min = 2 days     max_nodes = 20
leaf prototype_scale = 0.09–0.12 m (library default)
```

Nodes are spaced 2.5 cm apart under 10–16 cm leaflets, so each leaf spans **four to six times its own
spacing** and leaves stack in dense overlapping layers. Real cowpea runs 5–10 cm internodes against
comparable leaflets. The model reaches the correct plant *height* by packing roughly twice the real
number of nodes into it.

Consequences we measured: apparent leaf size 53.8 px against a real 75.9, and 1.6× too many visible
leaves at matched canopy cover. Correcting internode length (with phyllochron and max_nodes, to hold
height) took leaf size to **74.5–76.4**, essentially exact.

For 3D fitting this is central: if you fit node positions to a scan, this default fights you, and a
fit that reproduces plant height can still have the wrong node count. **Fit internode length and node
count together and check leaf-size-to-spacing, not just height.**

### 1.5 The library never sets a leaf angle distribution

Measured mean leaf inclination is **48.0°**, and a uniform distribution gives **48.3°** — it is the
default falling through, not a property of cowpea, which is planophile at roughly 30–35°.

`setPlantLeafAngleDistribution(plantIDs, Beta_mu, Beta_nu, eccentricity, rotation)` follows the
Goel–Strebel convention, verified by measurement:

| μ, ν | mean inclination |
|---|---|
| 2.770, 1.172 (planophile) | 33.4° |
| 1.101, 1.930 (spherical) | 56.8° |
| 1.172, 2.770 (erectophile) | 61.9° |
| 1.0, 1.0 (uniform) | 48.3° |

`getPlantLeafInclinationAngleDistribution(plantIDs, nbins)` measures it back. This is cheap — it is a
plant-model property, so it runs in a rasterized pass in ~20 s, no ray tracing needed.

Leaf angle drives light interception, so it is not only an appearance parameter. It also changes
photometric calibration — see §3.6.

### 1.6 The nitrogen model couples to leaf optics, and both are unused by default

`PlantArchitecture::enableNitrogenModel()` tracks per-leaf nitrogen and publishes it as object data
`leaf_nitrogen_gN_m2`; `LeafOptics::run(UUIDs, LeafOpticsProperties_Nauto)` reads exactly that label
and bins it into distinct PROSPECT spectra. Wiring the two together gives physically-driven leaf
colour variation instead of one spectrum for every leaf.

Traps we hit, in order:

- **Supply starvation.** Leaves draw from a per-plant pool. We swept target and rate for two grids
  while the pool was the binding constraint (`supply_ratio` 0.34) and neither parameter did anything.
  Size the supply generously and *verify* — we added a `DIAG supply_ratio` line for this.
- **`min(target, rate × age)`.** Below `rate × lifespan` the target never binds and half a grid is
  the same run.
- **Leaves created during growth start at ZERO nitrogen.** `initializeNitrogenPools` only seeds
  leaves existing when it is called, so the youngest render at zero chlorophyll — white-yellow. There
  is a `minimum_leaf_N_area` but it is not applied to them. Clamp it yourself, in `buildCanopy`,
  before the spectra are assigned.
- The skewed age distribution means the **median** leaf sits far below target, so target must be set
  well above the value you want the median to have.

### 1.7 `writePrimitiveDataLabelMap` is the most useful tool in the codebase

`RadiationModel::writePrimitiveDataLabelMap(camera, primitive_data_label, file, path)` writes a
per-pixel map of any primitive data, registered to the rendered image. Set a unique ID per leaf and
you have exact per-leaf masks; tag the ground and you have an exact soil mask.

Use it to **validate every inferential measurement before trusting it**. See §3.1 — this is the
single highest-value habit in the project, and every time we skipped it we lost a day.

---

## 2. Numbers worth keeping

Measured for this cowpea dataset (2592×2048 sensor, ~0.44 mm/px native, tiles cut at 1280 native and
downsampled 2× so tile pixels are ~0.88 mm).

| quantity | real | library default | after correction |
|---|---|---|---|
| leaf major axis (SAM, tile px) | 75.9 | 53.8 | 76.4 |
| canopy cover ÷ visible leaf count | 0.0139 | 0.0059 | 0.0115 |
| mean leaf inclination | — | 48.0° | 33.4° (planophile) |
| plant height (excl. peduncles) | 0.54 m | ~0.63 m | ~0.55 m |
| foliage median L* | 47.8 | — | calibrated per config |
| foliage hue | 123.5° | 117.2° (board CCM) | 123.3° (scene-fit CCM) |

Leaf-size measurement is only meaningful **at matched canopy cover** — segmentation reads truncated
fragments in a sealed canopy, so the same plants measure 1.46× small at cover 0.99 and 1.16× at 0.95.

---

## 3. Methodology — the expensive lessons

### 3.1 Validate the instrument where truth exists, before believing it across domains

Five methods were used to measure leaf size and gave 1.02×, 0.78×, 1.46×, 1.16× and finally the
truth. Granulometry sizes *bright structures*, and adjacent leaves of similar brightness merge, so a
canopy of many small overlapping leaves scores identically to one of few large ones. Edge-bounded
regions fragment with texture, and the real imagery has more of it, so it cut real leaves up more
than synthetic ones.

Only an audit against exact per-leaf masks settled it: SAM's size bias on matched pairs is **0.99×**
(sound), recall 52.8%, with both splitting and merging present. That audit takes about ten minutes
and should have come *before* any cross-domain number was quoted. It was prompted by the user asking
whether it had been done; it had not.

The same discipline had already caught an Excess Green vegetation classifier that called a frame of
0.30 true cover 0.98 — checked against exact masks on synthetic, where the answer is known.

### 3.2 Ask whether a parameter can move the ratio you care about, before sweeping it

The quantity that mattered was **cover ÷ leaf count**. Germination and canopy age both remove leaves
and cover *in lockstep* and leave it invariant: it read 0.0080, 0.0083, 0.0083, 0.0089 across a
canopy-age range that moved flower count from 15.5 to 0.33. Leaf scale moves it, but would have
needed a 0.24–0.43 m leaf.

Three sweeps and most of a day went into proportional levers. A five-minute dimensional argument —
*what is invariant under this parameter?* — would have skipped them. For 3D fitting, ask this of
every parameter before it enters an optimiser.

### 3.3 Stochastic parameters need enough draws

Germination is drawn *per scene*. A three-scene sweep gave flower density 7.39 against a real 7.57
and it went into the report as "solved"; ten scenes of the same configuration gave **5.37**. Cover
moved 0.923 → 0.794 the same way. Flower counts across a later sweep read 9.86 → 6.28 → 9.36, which
is not monotonic and is therefore noise.

Any parameter drawn per scene needs enough scenes that its own variance is below the effect you are
claiming. Three is almost never enough.

### 3.4 Put code where the consumer actually executes

Three failures in one day, all the same shape:

- A venation spectrum registered *after* `leafoptics.run()` had already read the data.
- A nitrogen floor applied in the render path, while the geom pass — used for calibration — never
  executed it, and the diagnostic printed pre-clamp values.
- An import placed above the `sys.path.insert` that makes the package importable.

Each cost a job. The tell in two of them was **suspiciously identical output** across settings that
should have differed; treat that as a disconnected code path, not a weak effect. Add a guard that
makes a no-op visible — we added `primitives_raised=` to the diagnostic and made the sweep abort if a
clamp raised nothing.

### 3.5 Caches and constants go stale silently

The evaluation cache keys on overrides, frames and seeds — **not** on code version, so a re-run after
changing the colour pipeline silently returns the old number. Use a fresh seed to force re-evaluation
when the code has changed.

Similarly: a CMake cache pointed at a Vulkan SDK path that had moved; a log string hard-coded a ratio
that went stale twice (fixed properly by *deriving* it from the constants); and a gain of 575.9 was
hard-coded in nine files. Prefer one authoritative definition, and derive anything displayed.

### 3.6 Calibrations are coupled — photometric calibration depends on geometry

The exposure gain is bisected so foliage lands at the real median lightness. Planophile leaves are
more nearly horizontal, intercept more light, and render brighter: the gain calibrated for a 48°
canopy (648.7) gave foliage at L* 62.6 instead of 47.8 on a 33° canopy, which needs 374.0.

**Any change to leaf angle, canopy density or architecture invalidates the exposure calibration.**
Carry the *target* (`REAL_FOLIAGE_L`) between configurations, never the gain. Thirteen scripts were
passing a fixed gain, so several sweeps rendered mis-exposed images.

### 3.7 State predictions before the run, so they can fail

The hypothesis that an over-drawn midrib was splitting leaves was written into the script as
"expect major ~78 px and ~64 leaves/tile". It returned 1.00× and 1.12×. Clean falsification, no
argument.

It had come from a numerical coincidence — a count ratio of 1.88 and a size ratio of 1.375, with
√1.88 = 1.371 — that was compelling and wrong. It also failed to reproduce in another configuration,
which was visible at the time and should have been weighted more heavily.

### 3.8 Fidelity and task performance are different objectives, and can oppose each other

Measured twice. A configuration matching real flower density scored **0.098 mAP worse at 10.9 SE**
than one with 3–4× too many flowers, because a detector trains on labelled examples and realism caps
how many an image can hold. Across eight diverse configurations, the rank correlation between an
appearance/geometry objective and detection was −0.07.

This may not apply to your problem — fitting a scan *is* a fidelity objective — but the general form
does: **decide which quantity you are optimising and validate against that quantity**, not against a
proxy that seems obviously related. Every cheap proxy tried here failed to predict the thing we cared
about, including ones that looked mechanistically sound.

### 3.9 Trust the human's visual read

The user said leaves looked too small. Granulometry said 1.02×, i.e. matched. The user pushed back,
asked for a second method, and was right — the eventual measurement was 1.4×, and the cause was an
unexposed library default. Earlier the same thing happened with leaf colour: the user said young
leaves were too yellow and there were too many of them, and a lightness-relative metric said the
count was *fewer* than real. Measured on hue rather than lightness, the user was right on both.

A trained eye integrates over things a summary statistic discards. When a measurement contradicts a
domain expert, suspect the measurement first.

---

## 4. What transfers to 3D scan fitting, and what does not

**Transfers directly**

- Everything in §1. The compound-leaf/leaflet distinction (§1.1) and the internode spacing default
  (§1.4) are likely to be your first two obstacles.
- §3.2 — ask what each parameter leaves invariant. In a fitting context, a parameter that cannot move
  a residual will simply waste optimiser iterations and may hide behind a plausible-looking loss.
- §3.4, §3.5 — the same code and cache traps.
- Per-plant architecture setters do not exist (§1.3). For fitting individual plants this is probably
  the first thing you need to add.

**Changes shape**

- Instrument validation (§3.1) gets *easier*: a 3D scan is closer to ground truth than an image, and
  you can compare geometry to geometry. But you still need to validate the **correspondence** —
  which scan segment is which model organ — and that is exactly where the compound-leaf trap lies.
- Stochastic sampling (§3.3) mostly disappears for single-plant fitting, but returns the moment you
  evaluate a fitted parameter set by generating a population.
- Photometric coupling (§3.6) is irrelevant if you never render. If you *do* render to compare
  against imagery, it returns in full.

**Probably does not transfer**

- The fidelity-versus-utility opposition (§3.8). Fitting a scan has fidelity as its objective. Keep
  it in mind only if the fitted model is later used to generate training data — at which point the
  most faithful plant may not be the most useful one.

---

## 5. Where things are

| what | where |
|---|---|
| Full technical report | `audit/syn2real_report.html` (published as a Claude artifact) |
| Best detection configuration | `audit/phase5_confirm.json`, trial 18 — the only config with measured mAP |
| Best fidelity configuration | `audit/best_fidelity.json` + §18 of the report |
| Leaf size by segmentation | `scripts/sam_leaf_size.py`, audited by `scripts/sam_mask_audit.py` |
| Leaf colour metric | `syn2real/leafcolour.py` |
| Camera chain replica | `syn2real/camera_pipeline.py` — mirrors `RadiationCamera` operation for operation |
| Detection evaluation | `syn2real/map_objective.py` |
| Exposure target | `camera_pipeline.REAL_FOLIAGE_L` — carry this, not a gain |

Diagnostics added to `main.cpp` worth keeping: `DIAG leafN`, `DIAG nitrogen_floor`,
`DIAG leaf_inclination`, `DIAG plant_height`, `DIAG nitrogen ... supply_ratio`, and the
`output.write_leaf_ids` per-leaf mask map.
