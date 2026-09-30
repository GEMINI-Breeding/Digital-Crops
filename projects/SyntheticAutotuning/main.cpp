#include "LeafOptics.h"
#include "PlantArchitecture.h"
#include "Assets.h"  // must follow PlantArchitecture.h: it uses types declared there
#include "RadiationModel.h"
#include "SyntheticAnnotation.h"
#include "Visualizer.h"
#include "config.h"
#include "json.hpp"

#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <limits>
#include <iostream>
#include <random>
#include <set>
#include <sstream>
#include <string>
#include <vector>

using namespace helios;

namespace {

// ------------------------------------------------------------ site seeding ---

// A plant's random stream should be a function of its own site and nothing else.
//
// PlantArchitecture draws every random value -- bud break, internode length, leaf angle, which
// prototype a leaf gets -- from the one generator the Context owns. Grown together, the plants
// share that single stream: plant 7's leaves depend on how many draws plants 0-6 consumed, and
// any change upstream (one more node on plant 2, a plant added at site 4) re-deals every plant
// after it. The scene is then discontinuous in its parameters, which is what makes fitting it
// to one real image hard: a candidate cannot be changed at one site without the rest of the
// field changing with it.
//
// Reseeding the Context generator from a hash of (site seed, purpose) before each plant is
// built and again before it is grown -- and growing the plants one at a time -- breaks that
// coupling. Plant k then depends on (parameters, site seed) alone, so a site can be re-drawn,
// re-aged or removed and its neighbours are reproduced bit for bit.
uint64_t splitmix64(uint64_t x) {
    x += 0x9E3779B97F4A7C15ULL;
    x = (x ^ (x >> 30)) * 0xBF58476D1CE4E5B9ULL;
    x = (x ^ (x >> 27)) * 0x94D049BB133111EBULL;
    return x ^ (x >> 31);
}

//! Deterministic Context seed from (stream, purpose), in the range std::minstd_rand0 accepts.
uint hashSeed(unsigned stream, int purpose) {
    const uint64_t h = splitmix64(splitmix64(uint64_t(stream)) ^ (uint64_t(purpose) + 1u) * 0xD1B54A32D192ED03ULL);
    return uint(h % 2147483646ULL) + 1u;
}

//! Uniform [0,1) draw from (stream, purpose), for decisions taken outside the plant model.
float hashUniform(unsigned stream, int purpose) {
    return float(hashSeed(stream, purpose) - 1u) / 2147483646.f;
}

//! One planting site: where a plant stands, how it is turned, how old it is, and the seed of its own random stream.
struct Site {
    vec3 position;
    float yaw_rad = -1.f; //!< < 0: draw from the shared Context stream after growth (legacy behaviour)
    float age_days = 0.f;
    unsigned seed = 0; //!< identity of the plant: the same (parameters, seed, age) reproduce the same plant at any site
    uint plantID = 0;
};

// ---------------------------------------------------------------- prospect ---

//! Dump PROSPECT spectra for a sample of pigment parameter sets, so the fit that
//! chooses cowpea leaf pigments runs against the SAME model the renderer uses.
int dumpProspectGrid(int n_samples, unsigned seed, const std::string &outfile) {
    Context context;
    LeafOptics leafoptics(&context);
    struct Range { float lo, hi; };
    const Range Cab{10.f, 80.f}, Car{2.f, 25.f}, Cant{0.f, 10.f}, N{1.0f, 2.5f};
    const Range Cw{0.005f, 0.025f}, Cdm{0.003f, 0.012f};
    std::mt19937 rng(seed);
    std::uniform_real_distribution<float> U(0.f, 1.f);
    auto samp = [&](const Range &r) { return r.lo + U(rng) * (r.hi - r.lo); };
    const int lo_nm = 400, hi_nm = 750;

    std::ofstream f(outfile);
    if (!f) { std::cerr << "ERROR: cannot open " << outfile << std::endl; return 1; }
    f << "# Cab Car Cant N Cw Cdm | R(400..750) | T(400..750)\n";
    f << lo_nm << " " << hi_nm << " " << n_samples << "\n";
    for (int s = 0; s < n_samples; s++) {
        LeafOpticsProperties p;
        p.chlorophyllcontent = samp(Cab); p.carotenoidcontent = samp(Car);
        p.anthocyancontent = samp(Cant);  p.numberlayers = samp(N);
        p.watermass = samp(Cw);           p.drymass = samp(Cdm);
        p.brownpigments = 0.f; p.protein = 0.f; p.carbonconstituents = 0.f;
        std::vector<vec2> R, T;
        leafoptics.getLeafSpectra(p, R, T);
        f << p.chlorophyllcontent << " " << p.carotenoidcontent << " " << p.anthocyancontent << " "
          << p.numberlayers << " " << p.watermass << " " << p.drymass;
        for (const auto &v: R) if (v.x >= lo_nm && v.x <= hi_nm) f << " " << v.y;
        for (const auto &v: T) if (v.x >= lo_nm && v.x <= hi_nm) f << " " << v.y;
        f << "\n";
    }
    std::cout << "wrote " << n_samples << " spectra to " << outfile << std::endl;
    return 0;
}

// ------------------------------------------------------------------ flowers ---

// Size of the closed-flower (bud) mesh relative to the open corolla. Set from the config before
// the canopy is built; the prototype function signature is fixed by PlantArchitecture, so it
// cannot be passed in as an argument.
float closed_flower_scale = 1.f;

uint CowpeaFlowerPrototype_custom(Context *ctx, uint subdivisions, bool flower_is_open) {
    std::vector<uint> UUIDs;
    uint objID;
    if (flower_is_open) {
        if (ctx->randu() < 0.7) {
            UUIDs = ctx->loadOBJ("plugins/plantarchitecture/assets/obj/CowpeaFlower_open_highres.obj",
                                 make_vec3(0, 0, 0), 0, nullrotation, RGB::black, "ZUP", true);
            objID = ctx->addPolymeshObject(UUIDs);
        } else {
            UUIDs = ctx->loadOBJ("plugins/plantarchitecture/assets/obj/CowpeaFlower_senescent_highres.obj",
                                 make_vec3(0, 0, 0), 0, nullrotation, RGB::black, "ZUP", true);
            objID = ctx->addPolymeshObject(UUIDs);
            ctx->setObjectData(objID, "senescent_flower", 1);
        }
    } else {
        UUIDs = ctx->loadOBJ("plugins/plantarchitecture/assets/obj/CowpeaFlower_closed_highres.obj",
                             make_vec3(0, 0, 0), 0, nullrotation, RGB::black, "ZUP", true);
        objID = ctx->addPolymeshObject(UUIDs);
        // The closed and open meshes share one flower_prototype_scale, and in prototype units the
        // bud is 0.47 of the corolla: with the corolla at its correct 30 mm the bud renders 14 mm.
        // Measured on the real annotations that ratio is 0.91 (elongated boxes 30.4 px against
        // compact ones 33.5 px) -- a cowpea bud about to open is nearly as long as the flower it
        // becomes, and it is that stage, not an immature primordium, that an annotator marks.
        // Scaled here rather than through flower_prototype_scale, which would take the open
        // flowers with it.
        if (closed_flower_scale != 1.f) {
            ctx->scaleObjectAboutPoint(objID, make_vec3(closed_flower_scale, closed_flower_scale, closed_flower_scale), make_vec3(0, 0, 0));
        }
    }
    return objID;
}

// ----------------------------------------------------------------- species ---

// Species switch (2026-09-29, block C). canopy.species names the Helios plant-library model the canopy is built from;
// absent, it is cowpea, the model every twin fit so far was made with, and every cowpea code path below is unchanged.
// Each library species registers its own shoot types, and the twin's shoot-parameter overrides go to the species'
// main shoot type from this table (cowpea's trifoliate; sorghum and tomato grow everything from "mainstem").
std::string plantSpecies(const Config &cfg) {
    return cfg.s("canopy.species", "cowpea");
}

std::string mainShootType(const std::string &species) {
    static const std::map<std::string, std::string> table = {
            {"cowpea", "trifoliate"}, {"sorghum", "mainstem"}, {"tomato", "mainstem"}};
    const auto it = table.find(species);
    if (it == table.end()) {
        helios_runtime_error("ERROR: canopy.species '" + species + "' has no shoot-type entry; known: cowpea, sorghum, tomato.");
    }
    return it->second;
}

//! The library's own phenology thresholds per species (dormancy break, flower initiation, flower opening, fruit set,
//! fruit maturity, dormancy), as build<Species>Plant sets them; used for any phenology.* key a non-cowpea config omits.
std::vector<float> libraryPhenology(const std::string &species) {
    if (species == "sorghum") return {0.f, -1.f, -1.f, 4.f, 35.f, 1000.f};   // PlantLibrary.cpp buildSorghumPlant
    if (species == "tomato") return {0.f, 40.f, 5.f, 5.f, 30.f, 1000.f};     // PlantLibrary.cpp buildTomatoPlant
    return {0.f, 40.f, 5.f, 5.f, 30.f, 1000.f};
}

// Builds the cowpea canopy: shoot parameters, plant instances on the bed grid, and the growth
// advance. Shared by the ray-traced camera path and the rasterized geometry path so that a
// geometry parameter tuned against the fast rasterizer means the same thing in a full render.
//! Load the library cowpea model and apply every shoot-parameter override in the config. Shared by
//! buildCanopy() and loadCanopyXML(): a plant-structure XML is rebuilt from the shoot types registered
//! here (leaf prototype, petiole radius, flower prototype), so a loaded plant must see the same ones a
//! grown plant does. Returns canopy.library_defaults.
bool configurePlantModel(const Config &cfg, PlantArchitecture &plantarchitecture) {

    // --- plant model --------------------------------------------------------
    plantarchitecture.optionalOutputObjectData("plantID");
    plantarchitecture.optionalOutputObjectData("openflowerID");
    plantarchitecture.optionalOutputObjectData("closedflowerID");
    plantarchitecture.optionalOutputObjectData("fruitID");
    // Ground clipping deletes any leaf with a vertex below z = 0. Off by default since 2026-09-15: a leaf dipping into the
    // soil looks better than a missing one, and on the fitted scenes clipping removed about one leaf per scene
    // (canopy.ground_clipping 1 restores it).
    if (cfg.i("canopy.ground_clipping", 0) != 0) {
        plantarchitecture.enableGroundClipping(0.);
    }
    const std::string species = plantSpecies(cfg);
    const bool cowpea = species == "cowpea";
    const std::string shoot_type = mainShootType(species);
    plantarchitecture.loadPlantModelFromLibrary(species);

    // The untuned reference: every shoot parameter and the phenology thresholds as the library
    // ships them, none of the overrides below from either project. Used for the naive baseline
    // the twin is compared against.
    const bool library_defaults = cfg.i("canopy.library_defaults", 0) != 0;
    if (library_defaults) {
        std::cout << "DIAG library_defaults=1 (no shoot-parameter or phenology overrides)" << std::endl;
    }
    ShootParameters sp = plantarchitecture.getCurrentShootParameters(shoot_type);
    if (!library_defaults) {
    // Species guards: the cowpea-only settings (petiole radius, scanned leaflet OBJ, the leaflet size default, the
    // flower block with its custom prototype) apply to cowpea alone. Another species keeps its library prototypes, and
    // the flat numeric keys below apply to it only when its config gives them.
    if (cowpea) {
    sp.phytomer_parameters.petiole.radius = 0.002;
    }
    // High-resolution scanned leaf meshes (~1,600 triangles per leaflet, with an
    // alpha cut-out texture) instead of the procedural leaf generator. Much
    // slower -- scene primitive count rises roughly 10x -- but it is what the
    // baseline dataset used, so any visual comparison against that set has to
    // use it too.
    if (cfg.i("leaf.use_obj_mesh", 0)) {
        if (!cowpea) {
            helios_runtime_error("ERROR (configurePlantModel): leaf.use_obj_mesh 1 loads the scanned cowpea leaflet meshes; "
                                 "canopy.species " + species + " keeps its library leaf prototype (set leaf.use_obj_mesh 0).");
        }
        sp.phytomer_parameters.leaf.prototype.prototype_function = CowpeaLeafPrototype_trifoliate_OBJ;
    }
    // Inflorescence pitch was previously pinned to a flat 90 deg, which stood every
    // bud erect and skewed rendered box log-aspect to -0.615 against a real +0.041.
    // Leaf size was never exposed and sat at the library default of uniform(0.09, 0.12) m
    // throughout, which is a botanically reasonable cowpea leaflet but not necessarily the right
    // one for these plots. Leaf-scale granulometry puts synthetic canopy structure ~19% smaller
    // than real, and this is the parameter that moves it.
    if (cowpea || cfg.has("leaf.prototype_scale_max")) {
    sp.phytomer_parameters.leaf.prototype_scale.uniformDistribution(
            cfg.f("leaf.prototype_scale_min", cowpea ? 0.09f : cfg.f("leaf.prototype_scale_max")), cfg.f("leaf.prototype_scale_max", 0.12f));
    }

    // Stem architecture. The library packs a trifoliate leaf with 0.10-0.16 m leaflets onto nodes
    // spaced only 0.025 m apart, so each leaf spans 4-6 times its own spacing and the leaves stack
    // in dense overlapping layers. Real cowpea runs 5-10 cm internodes against comparable leaflets,
    // a ratio nearer 1-2.
    //
    // That ratio is what makes the canopy show 1.6x too many leaves at the same cover, and no
    // previously exposed parameter moves it: germination and canopy age remove leaves and cover
    // together, and leaf scale alone would need a 0.24-0.43 m leaf to compensate. Node count and
    // internode length must move together to hold plant height, which is pinned at a measured
    // 0.54 m -- 20 nodes x 0.025 m today.
    if (cfg.f("canopy.internode_length_max", 0.f) > 0.f) {
        sp.internode_length_max = cfg.f("canopy.internode_length_max");
    }
    if (cfg.f("canopy.phyllochron", 0.f) > 0.f) {
        sp.phyllochron_min = cfg.f("canopy.phyllochron");
    }
    if (cfg.i("canopy.max_nodes", 0) > 0) {
        sp.max_nodes = cfg.i("canopy.max_nodes");
    }
    // How the plant spreads. Per-plant footprint IoU saturates at about 0.50 however many realizations are drawn --
    // 64x the seeds buys 0.01-0.04 -- while matching real plants against each other reaches 0.63, so roughly 0.2 of
    // IoU is model-side headroom rather than search. Footprint shape is mostly branch geometry, and none of these had
    // ever been exposed, let alone fitted: they set how far branches leave the stem, how that changes up the plant,
    // how the stem itself curves, and how the leaves are spaced around it. All optional -- absent means the library's
    // own value, so leaving them out reproduces every fit made before they existed.
    if (cfg.has("canopy.insertion_angle_tip")) {
        sp.insertion_angle_tip = cfg.f("canopy.insertion_angle_tip");
    }
    if (cfg.has("canopy.insertion_angle_decay")) {
        sp.insertion_angle_decay_rate = cfg.f("canopy.insertion_angle_decay");
    }
    if (cfg.has("canopy.internode_length_decay")) {
        sp.internode_length_decay_rate = cfg.f("canopy.internode_length_decay");
    }
    if (cfg.has("canopy.gravitropic_curvature")) {
        sp.gravitropic_curvature = cfg.f("canopy.gravitropic_curvature");
    }
    if (cfg.has("canopy.tortuosity")) {
        sp.tortuosity = cfg.f("canopy.tortuosity");
    }
    if (cfg.has("canopy.phyllotactic_angle")) {
        sp.phytomer_parameters.internode.phyllotactic_angle = cfg.f("canopy.phyllotactic_angle");
    }
    // Petiole droop and how leaf expansion is paced against internode elongation, both new in Helios 1.3.87. A petiole
    // that arches under its leaflets carries them inward and downward, which changes the footprint a nadir camera sees
    // without changing a single length.
    if (cfg.has("leaf.petiole_flexibility")) {
        sp.phytomer_parameters.petiole.flexibility = cfg.f("leaf.petiole_flexibility");
    }
    if (cfg.has("leaf.petiole_curvature")) {
        sp.phytomer_parameters.petiole.curvature = cfg.f("leaf.petiole_curvature");
    }
    if (cfg.f("canopy.leaf_expansion_rate", 0.f) > 0.f) {
        sp.leaf_expansion_rate_max = cfg.f("canopy.leaf_expansion_rate");
    }
    if (cfg.f("canopy.elongation_rate", 0.f) > 0.f) {
        sp.elongation_rate_max = cfg.f("canopy.elongation_rate");
    }

    // Branching. A plant's leaf count is set as much by how readily its lateral buds break as by how fast nodes appear
    // on any one shoot: the cowpea library gives a 0.25 probability at the tip decaying by -0.4 per node down the
    // shoot, with buds breaking 10 days after the node forms. With leaf size and petiole length pinned by hand labels,
    // and the cover deficit growing with canopy age (-10 % at 27 days, -16 % at 33), leaf production is what is left to
    // move, and phyllochron alone changes only where nodes appear on the shoots that already exist.
    if (cfg.has("canopy.bud_break_probability")) {
        sp.vegetative_bud_break_probability_min = cfg.f("canopy.bud_break_probability");
    }
    if (cfg.has("canopy.bud_break_decay")) {
        sp.vegetative_bud_break_probability_decay_rate = cfg.f("canopy.bud_break_decay");
    }
    if (cfg.has("canopy.bud_break_time")) {
        sp.vegetative_bud_break_time = cfg.f("canopy.bud_break_time");
    }
    // Seedling shape. A young cowpea's silhouette is set by how far its petioles carry the
    // leaflets from the stem and how flat they lie, which the library fixes at 0.10-0.14 m and
    // 20-50 deg. Exposed so that a single-image fit can move them: at the sparse growth stages
    // every plant is seen whole, and these are the parameters its outline is most sensitive to.
    if (cfg.f("leaf.petiole_length_max", 0.f) > 0.f) {
        sp.phytomer_parameters.petiole.length.uniformDistribution(
                cfg.f("leaf.petiole_length_min", cfg.f("leaf.petiole_length_max")), cfg.f("leaf.petiole_length_max"));
    }
    if (cfg.has("leaf.petiole_pitch_max")) {
        sp.phytomer_parameters.petiole.pitch.uniformDistribution(
                cfg.f("leaf.petiole_pitch_min", cfg.f("leaf.petiole_pitch_max")), cfg.f("leaf.petiole_pitch_max"));
    }
    if (cfg.has("leaf.pitch_std")) {
        sp.phytomer_parameters.leaf.pitch.normalDistribution(cfg.f("leaf.pitch_mean", 0.f), cfg.f("leaf.pitch_std"));
    }
    // Leaflet shape and posture, which a nadir view sees as leaflet width: the seedlings' leaflets are broad and flat, the
    // library's (aspect 0.7, midrib fold 0.2, lateral curvature -0.4) come out narrow from above. Each key applies only
    // when given, so configurations written before these existed reproduce unchanged.
    if (cfg.has("leaf.aspect_ratio")) {
        sp.phytomer_parameters.leaf.prototype.leaf_aspect_ratio = cfg.f("leaf.aspect_ratio");
    }
    if (cfg.has("leaf.midrib_fold_fraction")) {
        sp.phytomer_parameters.leaf.prototype.midrib_fold_fraction = cfg.f("leaf.midrib_fold_fraction");
    }
    if (cfg.has("leaf.lateral_curvature")) {
        sp.phytomer_parameters.leaf.prototype.lateral_curvature = cfg.f("leaf.lateral_curvature");
    }
    if (cfg.has("leaf.longitudinal_curvature_max")) {
        sp.phytomer_parameters.leaf.prototype.longitudinal_curvature.uniformDistribution(
                cfg.f("leaf.longitudinal_curvature_min", cfg.f("leaf.longitudinal_curvature_max")), cfg.f("leaf.longitudinal_curvature_max"));
    }
    // Where the lateral leaflets sit along the rachis (fraction of leaflet length) and their size relative to the terminal one.
    if (cfg.has("leaf.leaflet_offset")) {
        sp.phytomer_parameters.leaf.leaflet_offset = cfg.f("leaf.leaflet_offset");
    }
    if (cfg.has("leaf.leaflet_scale")) {
        sp.phytomer_parameters.leaf.leaflet_scale = cfg.f("leaf.leaflet_scale");
    }
    // Petiole bend (deg/m, negative droops) and stem inclination, which decide whether leaves radiate as spokes or sit along a stem.
    if (cfg.has("leaf.petiole_curvature_max")) {
        sp.phytomer_parameters.petiole.curvature.uniformDistribution(
                cfg.f("leaf.petiole_curvature_min", cfg.f("leaf.petiole_curvature_max")), cfg.f("leaf.petiole_curvature_max"));
    }
    if (cfg.has("canopy.internode_pitch")) {
        sp.phytomer_parameters.internode.pitch = cfg.f("canopy.internode_pitch");
    }

    if (cowpea) {
    sp.phytomer_parameters.inflorescence.pitch.uniformDistribution(
            cfg.f("flower.inflorescence_pitch_min"), cfg.f("flower.inflorescence_pitch_max"));
    sp.phytomer_parameters.inflorescence.flower_prototype_scale = cfg.f("flower.prototype_scale");
    sp.phytomer_parameters.peduncle.length.uniformDistribution(
            cfg.f("flower.peduncle_length_min"), cfg.f("flower.peduncle_length_max"));
    sp.phytomer_parameters.inflorescence.flowers_per_peduncle.uniformDistribution(
            cfg.i("flower.flowers_per_peduncle_min"), cfg.i("flower.flowers_per_peduncle_max"));
    sp.phytomer_parameters.inflorescence.flower_offset = cfg.f("flower.flower_offset", 0.05f);
    sp.flower_bud_break_probability.uniformDistribution(
            cfg.f("flower.bud_break_prob_min"), cfg.f("flower.bud_break_prob_max"));
    sp.fruit_set_probability = cfg.f("flower.fruit_set_probability");
    closed_flower_scale = cfg.f("flower.closed_scale", 1.0f);
    sp.phytomer_parameters.inflorescence.flower_prototype_function = CowpeaFlowerPrototype_custom;
    sp.phytomer_parameters.inflorescence.unique_prototypes = 20;
    } else {
        // Non-cowpea: the library's own flower and fruit prototypes (sorghum panicle; tomato flower and fruit), each
        // inflorescence key applied only when given.
        if (cfg.has("flower.inflorescence_pitch_max")) {
            sp.phytomer_parameters.inflorescence.pitch.uniformDistribution(
                    cfg.f("flower.inflorescence_pitch_min", cfg.f("flower.inflorescence_pitch_max")), cfg.f("flower.inflorescence_pitch_max"));
        }
        if (cfg.has("flower.prototype_scale")) {
            sp.phytomer_parameters.inflorescence.flower_prototype_scale = cfg.f("flower.prototype_scale");
        }
        if (cfg.has("fruit.prototype_scale")) {
            sp.phytomer_parameters.inflorescence.fruit_prototype_scale = cfg.f("fruit.prototype_scale");
        }
        if (cfg.has("flower.peduncle_length_max")) {
            sp.phytomer_parameters.peduncle.length.uniformDistribution(
                    cfg.f("flower.peduncle_length_min", cfg.f("flower.peduncle_length_max")), cfg.f("flower.peduncle_length_max"));
        }
        if (cfg.has("flower.flowers_per_peduncle_max")) {
            sp.phytomer_parameters.inflorescence.flowers_per_peduncle.uniformDistribution(
                    cfg.i("flower.flowers_per_peduncle_min", cfg.i("flower.flowers_per_peduncle_max")), cfg.i("flower.flowers_per_peduncle_max"));
        }
        if (cfg.has("flower.flower_offset")) {
            sp.phytomer_parameters.inflorescence.flower_offset = cfg.f("flower.flower_offset");
        }
        if (cfg.has("flower.bud_break_prob_max")) {
            sp.flower_bud_break_probability.uniformDistribution(
                    cfg.f("flower.bud_break_prob_min", cfg.f("flower.bud_break_prob_max")), cfg.f("flower.bud_break_prob_max"));
        }
        if (cfg.has("flower.fruit_set_probability")) {
            sp.fruit_set_probability = cfg.f("flower.fruit_set_probability");
        }
    }
    plantarchitecture.updateCurrentShootParameters(shoot_type, sp);
    } // !library_defaults
    return library_defaults;
}

// Leaf chlorophyll without the nitrogen model, per trifoliate leaf: the leaflets on one petiole are the same age and share one
// value, Cab = leaf.chlorophyll * (y + (1 - y) * min(1, age / leaf.chlorophyll_mature_age)) + N(0, leaf.chlorophyll_sd), with
// y = leaf.chlorophyll_young_fraction (young leaves paler; 1 = no age effect), plus an optional small per-leaflet jitter
// (leaf.chlorophyll_leaflet_sd), clamped to leaf.chlorophyll_min..max. Published as the leaf nitrogen the binned PROSPECT path
// reads. Draws come from each plant's own stream, so a plant's colours depend only on its site seed.
void assignLeafChlorophyll(const Config &cfg, Context &context, PlantArchitecture &plantarchitecture, const std::vector<uint> &plantIDs,
                           const std::vector<Site> &sites) {
    const bool leaf_cab_variation = cfg.f("leaf.chlorophyll_sd", 0.f) > 0.f || cfg.f("leaf.chlorophyll_young_fraction", 1.f) < 1.f;
    if (!leaf_cab_variation) return;
    if (cfg.i("leaf.nitrogen_model", 0)) {
        helios_runtime_error("ERROR (buildCanopy): leaf chlorophyll variation and leaf.nitrogen_model both set leaf nitrogen; use one.");
    }
    const float cab_per_N = 100.f * cfg.f("leaf.f_photosynthetic", 0.50f) * cfg.f("leaf.N_to_Cab_coefficient", 0.40f);
    const float cab_mature = cfg.f("leaf.chlorophyll"), young = cfg.f("leaf.chlorophyll_young_fraction", 1.f);
    const float mature_age = std::max(cfg.f("leaf.chlorophyll_mature_age", 8.f), 1e-3f);
    const float leaf_sd = cfg.f("leaf.chlorophyll_sd", 0.f), leaflet_sd = cfg.f("leaf.chlorophyll_leaflet_sd", 0.f);
    const float cab_min = cfg.f("leaf.chlorophyll_min", 20.f), cab_max = cfg.f("leaf.chlorophyll_max", 100.f);
    std::vector<float> drawn;
    for (size_t k = 0; k < plantIDs.size(); k++) {
        const unsigned stream = k < sites.size() ? sites[k].seed : unsigned(k + 1);
        std::mt19937 rng(hashSeed(stream, 7));
        std::normal_distribution<float> unit(0.f, 1.f);
        for (uint shootID: plantarchitecture.getAllShootIDs(plantIDs[k])) {
            if (plantarchitecture.isShootPruned(plantIDs[k], shootID)) continue;
            for (const auto &phytomer: plantarchitecture.getPlantShoot(plantIDs[k], shootID)->phytomers) {
                const float age_factor = young + (1.f - young) * std::min(1.f, phytomer->age / mature_age);
                for (const std::vector<uint> &leaflets: phytomer->leaf_objIDs) {
                    const float leaf_cab = cab_mature * age_factor + leaf_sd * unit(rng);
                    for (uint objID: leaflets) {
                        if (!context.doesObjectExist(objID)) continue;
                        const float value = std::clamp(leaf_cab + leaflet_sd * unit(rng), cab_min, cab_max);
                        context.setObjectData(objID, "leaf_nitrogen_gN_m2", value / cab_per_N);
                        drawn.push_back(value);
                    }
                }
            }
        }
    }
    std::sort(drawn.begin(), drawn.end());
    auto q = [&](float f) { return drawn.empty() ? 0.f : drawn[size_t(f * float(drawn.size() - 1))]; };
    std::cout << "DIAG chlorophyll_per_leaf n=" << drawn.size() << " Cab_p10=" << q(0.1f) << " Cab_p50=" << q(0.5f) << " Cab_p90=" << q(0.9f) << std::endl;
}

// Tag every primitive with the index of its site, so that a per-pixel map of it can be written
// by either the ray tracer or the label rasterizer, and print the sites so the fitting code can
// name each plant in the scene by (position, yaw, age, seed) and reproduce it.
void tagSites(Context &context, PlantArchitecture &plantarchitecture, const std::vector<Site> &sites) {
    for (size_t k = 0; k < sites.size(); k++) {
        const Site &s = sites[k];
        context.setPrimitiveData(plantarchitecture.getAllPlantUUIDs(s.plantID), "siteIndex", int(k + 1));
        std::cout << "SITE " << k << " " << std::setprecision(9) << s.position.x << " " << s.position.y << " "
                  << rad2deg(s.yaw_rad) << " " << s.age_days << " " << s.seed << " " << s.plantID << std::endl;
    }
}

// diag.leafdump <path>: every leaf object's plant, index in the plant, primitive count, area, centroid and area-weighted normal, so
// that a grown canopy and the same canopy read back from XML can be compared organ by organ.
void dumpLeaves(const Config &cfg, Context &context, PlantArchitecture &plantarchitecture, const std::vector<uint> &plantIDs) {
    if (!cfg.has("diag.leafdump")) return;
    std::ofstream out(cfg.s("diag.leafdump"));
    // base: the attachment point the plant recorded (stale after a post-growth yaw); tip: the vertex farthest from it.
    out << "# plant leaf n_prims area cx cy cz nx ny nz bx by bz tx ty tz\n" << std::setprecision(9);
    for (size_t k = 0; k < plantIDs.size(); k++) {
        const std::vector<uint> leaves = plantarchitecture.getPlantLeafObjectIDs(plantIDs[k]);
        const std::vector<vec3> bases = plantarchitecture.getPlantLeafBases(plantIDs[k]);
        for (size_t i = 0; i < leaves.size(); i++) {
            const vec3 base = i < bases.size() ? bases[i] : make_vec3(0, 0, 0);
            vec3 tip = base;
            float area = 0.f;
            vec3 c(0, 0, 0), n(0, 0, 0);
            const std::vector<uint> prims = context.getObjectPrimitiveUUIDs(leaves[i]);
            for (uint u: prims) {
                const float a = context.getPrimitiveArea(u);
                const std::vector<vec3> v = context.getPrimitiveVertices(u);
                vec3 pc(0, 0, 0);
                for (const vec3 &p: v) {
                    pc = pc + p;
                    if ((p - base).magnitude() > (tip - base).magnitude()) tip = p;
                }
                c = c + pc / float(v.size()) * a;
                n = n + context.getPrimitiveNormal(u) * a;
                area += a;
            }
            if (area > 0.f) c = c / area;
            out << k << " " << i << " " << prims.size() << " " << area << " " << c.x << " " << c.y << " " << c.z << " " << n.x / std::max(area, 1e-12f) << " "
                << n.y / std::max(area, 1e-12f) << " " << n.z / std::max(area, 1e-12f) << " " << base.x << " " << base.y << " " << base.z << " " << tip.x << " "
                << tip.y << " " << tip.z << "\n";
        }
    }
}

// diag.leafxform <path>: every leaf object's transformation matrix as Helios stores it (row-major; origin in T[3], T[7], T[11]),
// one line per leaf with its site index and object ID, so a leaf's pose can be read from the object itself rather than
// measured off its vertices. Written after the per-plant yaw, where diag.leafruler writes.
void dumpLeafTransforms(const Config &cfg, Context &context, PlantArchitecture &plantarchitecture, const std::vector<uint> &plantIDs) {
    if (!cfg.has("diag.leafxform")) return;
    std::ofstream out(cfg.s("diag.leafxform"));
    if (!out) {
        helios_runtime_error("ERROR: cannot open diag.leafxform file " + cfg.s("diag.leafxform") + " for writing.");
    }
    out << "# plant objID T00 T01 T02 T03 T10 T11 T12 T13 T20 T21 T22 T23 T30 T31 T32 T33\n" << std::setprecision(9);
    size_t n = 0;
    for (size_t k = 0; k < plantIDs.size(); k++) {
        for (uint objID: plantarchitecture.getPlantLeafObjectIDs(plantIDs[k])) {
            if (!context.doesObjectExist(objID)) continue;
            float T[16];
            context.getObjectTransformationMatrix(objID, T);
            out << k << " " << objID;
            for (float t: T) out << " " << t;
            out << "\n";
            n++;
        }
    }
    std::cout << "DIAG leafxform leaves=" << n << " file=" << cfg.s("diag.leafxform") << std::endl;
}

// diag.leafverts <prefix>: every leaf object's world vertices (<prefix>_verts.f32, its primitives in UUID order, xyz float32)
// with an index (<prefix>_index.txt: site, objID, prototype index, leaf index on its petiole, leaves on that petiole, vertex
// count, the 16 transform entries). Copies of one prototype carry the same vertices in the same order, so mapping each leaf
// back through its own transform shows whether the transform still describes the geometry.
void dumpLeafVertices(const Config &cfg, Context &context, PlantArchitecture &plantarchitecture, const std::vector<uint> &plantIDs) {
    if (!cfg.has("diag.leafverts")) return;
    const std::string prefix = cfg.s("diag.leafverts");
    std::ofstream index(prefix + "_index.txt");
    std::ofstream verts(prefix + "_verts.f32", std::ios::binary);
    // I/O addition (2026-09-28): per-vertex texture UVs in the same order as _verts.f32 ((-1, -1) for a primitive
    // without texture coordinates), and each leaf's texture files, one line per leaf in _index.txt order.
    std::ofstream uvs(prefix + "_uv.f32", std::ios::binary);
    std::ofstream nvs(prefix + "_nv.u8", std::ios::binary);   // vertex count of each primitive, in _verts.f32 order
    std::ofstream texfile(prefix + "_tex.txt");
    texfile << "# plant objID texture_file(s) of its primitives, ';'-separated, '-' for none\n";
    index << "# plant objID prototype leaf n_leaves n_verts T00..T33\n" << std::setprecision(9);
    for (size_t k = 0; k < plantIDs.size(); k++) {
        for (uint shootID: plantarchitecture.getAllShootIDs(plantIDs[k])) {
            for (const auto &phytomer: plantarchitecture.getPlantShoot(plantIDs[k], shootID)->phytomers) {
                for (size_t p = 0; p < phytomer->leaf_objIDs.size(); p++) {
                    for (size_t l = 0; l < phytomer->leaf_objIDs[p].size(); l++) {
                        const uint objID = phytomer->leaf_objIDs[p][l];
                        if (!context.doesObjectExist(objID)) continue;
                        const int proto = (p < phytomer->leaf_prototype_index.size() && l < phytomer->leaf_prototype_index[p].size()) ? phytomer->leaf_prototype_index[p][l] : -9;
                        size_t n = 0;
                        std::set<std::string> textures;
                        for (uint u: context.getObjectPrimitiveUUIDs(objID)) {
                            const std::vector<vec3> pv = context.getPrimitiveVertices(u);
                            const std::vector<vec2> puv = context.getPrimitiveTextureUV(u);
                            const std::string tf = context.getPrimitiveTextureFile(u);
                            if (!tf.empty()) textures.insert(tf);
                            const uint8_t nv = uint8_t(pv.size());
                            nvs.write(reinterpret_cast<const char *>(&nv), 1);
                            for (size_t q = 0; q < pv.size(); q++) {
                                const vec3 &v = pv[q];
                                const float xyz[3] = {v.x, v.y, v.z};
                                verts.write(reinterpret_cast<const char *>(xyz), sizeof(xyz));
                                const float uv[2] = {q < puv.size() ? puv[q].x : -1.f, q < puv.size() ? puv[q].y : -1.f};
                                uvs.write(reinterpret_cast<const char *>(uv), sizeof(uv));
                                n++;
                            }
                        }
                        texfile << k << " " << objID << " ";
                        if (textures.empty()) texfile << "-";
                        for (auto it = textures.begin(); it != textures.end(); ++it) texfile << (it == textures.begin() ? "" : ";") << *it;
                        texfile << "\n";
                        float T[16];
                        context.getObjectTransformationMatrix(objID, T);
                        index << k << " " << objID << " " << proto << " " << l << " " << phytomer->leaf_objIDs[p].size() << " " << n;
                        for (float t: T) index << " " << t;
                        index << "\n";
                    }
                }
            }
        }
    }
    std::cout << "DIAG leafverts prefix=" << prefix << std::endl;
}

// diag.leafuvfit <path>: every leaf blade's pose read off its own geometry, independent of the prototype it was copied from:
// the least-squares affine fit world = O + U*u + V*(v - 0.5) of the blade's vertices against their texture coordinates.
// U runs along the midrib from base to tip (|U| = the blade length in the texture's frame), V across it, and O is the base
// on the midrib; rms_mm is how far the blade departs from that plane (curvature, fold, droop). Petiolules and veins are
// left out, as are primitives without texture coordinates or with the (0,0) placeholder at every vertex.
void dumpLeafUVFit(const Config &cfg, Context &context, PlantArchitecture &plantarchitecture, const std::vector<uint> &plantIDs) {
    if (!cfg.has("diag.leafuvfit")) return;
    std::ofstream out(cfg.s("diag.leafuvfit"));
    if (!out) {
        helios_runtime_error("ERROR: cannot open diag.leafuvfit file " + cfg.s("diag.leafuvfit") + " for writing.");
    }
    out << "# plant objID Ox Oy Oz Ux Uy Uz Vx Vy Vz rms_mm n_verts\n" << std::setprecision(9);
    size_t written = 0, skipped = 0;
    for (size_t k = 0; k < plantIDs.size(); k++) {
        for (uint objID: plantarchitecture.getPlantLeafObjectIDs(plantIDs[k])) {
            if (!context.doesObjectExist(objID)) continue;
            // Normal equations of xyz on (1, u, v - 0.5).
            double A[3][3] = {{0}}, B[3][3] = {{0}};
            std::vector<std::pair<vec3, vec2>> samples;
            for (uint u: context.getObjectPrimitiveUUIDs(objID)) {
                if (context.doesPrimitiveDataExist(u, "object_label")) {
                    std::string label;
                    context.getPrimitiveData(u, "object_label", label);
                    if (label == "petiolule" || label == "veins") continue;
                }
                const std::vector<vec2> uv = context.getPrimitiveTextureUV(u);
                const std::vector<vec3> xyz = context.getPrimitiveVertices(u);
                if (uv.size() != xyz.size()) continue;
                bool placeholder = true;
                for (const vec2 &t: uv) placeholder = placeholder && t.x == 0.f && t.y == 0.f;
                if (placeholder) continue;
                for (size_t i = 0; i < xyz.size(); i++) samples.emplace_back(xyz[i], uv[i]);
            }
            if (samples.size() < 3) {
                skipped++;
                continue;
            }
            for (const auto &s: samples) {
                const double f[3] = {1.0, s.second.x, s.second.y - 0.5};
                const double w[3] = {s.first.x, s.first.y, s.first.z};
                for (int i = 0; i < 3; i++) {
                    for (int j = 0; j < 3; j++) {
                        A[i][j] += f[i] * f[j];
                        B[i][j] += f[i] * w[j];
                    }
                }
            }
            // Solve A X = B (3x3, symmetric) by Cramer's rule; X rows are O, U, V.
            const double det = A[0][0] * (A[1][1] * A[2][2] - A[1][2] * A[2][1]) - A[0][1] * (A[1][0] * A[2][2] - A[1][2] * A[2][0]) +
                               A[0][2] * (A[1][0] * A[2][1] - A[1][1] * A[2][0]);
            if (std::fabs(det) < 1e-18) {
                skipped++;
                continue;
            }
            double inv[3][3];
            inv[0][0] = (A[1][1] * A[2][2] - A[1][2] * A[2][1]) / det;
            inv[0][1] = (A[0][2] * A[2][1] - A[0][1] * A[2][2]) / det;
            inv[0][2] = (A[0][1] * A[1][2] - A[0][2] * A[1][1]) / det;
            inv[1][0] = (A[1][2] * A[2][0] - A[1][0] * A[2][2]) / det;
            inv[1][1] = (A[0][0] * A[2][2] - A[0][2] * A[2][0]) / det;
            inv[1][2] = (A[0][2] * A[1][0] - A[0][0] * A[1][2]) / det;
            inv[2][0] = (A[1][0] * A[2][1] - A[1][1] * A[2][0]) / det;
            inv[2][1] = (A[0][1] * A[2][0] - A[0][0] * A[2][1]) / det;
            inv[2][2] = (A[0][0] * A[1][1] - A[0][1] * A[1][0]) / det;
            double X[3][3];
            for (int i = 0; i < 3; i++) {
                for (int j = 0; j < 3; j++) {
                    X[i][j] = inv[i][0] * B[0][j] + inv[i][1] * B[1][j] + inv[i][2] * B[2][j];
                }
            }
            double sq = 0.0;
            for (const auto &s: samples) {
                const double f[3] = {1.0, s.second.x, s.second.y - 0.5};
                const double w[3] = {s.first.x, s.first.y, s.first.z};
                for (int j = 0; j < 3; j++) {
                    const double r = w[j] - (f[0] * X[0][j] + f[1] * X[1][j] + f[2] * X[2][j]);
                    sq += r * r;
                }
            }
            out << k << " " << objID;
            for (int i = 0; i < 3; i++) {
                for (int j = 0; j < 3; j++) out << " " << X[i][j];
            }
            out << " " << std::sqrt(sq / double(samples.size())) * 1000.0 << " " << samples.size() << "\n";
            written++;
        }
    }
    std::cout << "DIAG leafuvfit leaves=" << written << " skipped=" << skipped << " file=" << cfg.s("diag.leafuvfit") << std::endl;
}

// diag.flowerdump <path>: every reproductive object (peduncle, closed flower, open flower, fruit) with the phytomer it
// belongs to -- (shoot, node) as diag.petiolecensus numbers them -- so a twin plant's flowers can be carried into
// another representation where the twin drew them. Called after the per-plant yaw, like leafruler and stalkdump, by
// the grown canopy (buildCanopy) and by the XML-loaded one (loadCanopyXML), so a plant read back from XML can be
// compared organ by organ with the plant it was written from.
//   peduncle   its centerline: the phytomer's stored peduncle vertices, which the yaw did not touch (it turns objects,
//              not plant state), turned here by the site's yaw about the plant base; check_mm is the largest distance
//              from a turned centerline point to the tube's own nearest vertex, i.e. about the tube radius when the
//              two agree.
//   inflorescence  the object's transformation matrix after scale, rotation, placement and yaw (its rotation and scale
//              are the organ's; its origin is NOT the attachment point when the prototype object itself carried a
//              translation), the world centroid of its vertices, and the attachment point the phytomer stored
//              (FloralBud::inflorescence_bases: the point on the peduncle), turned by the site's yaw.
// Line formats (world metres):
//   PED plant shoot node petiole bud terminal state objID radius_m n_pts x0 y0 z0 ... check_mm
//   INF plant shoot node petiole bud terminal state objID kind senescent peduncle_objID n_verts T00..T33 cx cy cz attach_ok ax ay az
void dumpFlowers(const Config &cfg, Context &context, PlantArchitecture &plantarchitecture, const std::vector<uint> &plantIDs,
                 const std::vector<Site> &sites) {
    if (!cfg.has("diag.flowerdump")) return;
    std::ofstream fd(cfg.s("diag.flowerdump"));
    if (!fd) {
        helios_runtime_error("ERROR: cannot open diag.flowerdump file " + cfg.s("diag.flowerdump") + " for writing.");
    }
    fd << std::setprecision(9);
    fd << "# PED plant shoot node petiole bud terminal state objID radius_m n_pts x y z ... check_mm\n";
    fd << "# INF plant shoot node petiole bud terminal state objID kind senescent peduncle_objID n_verts T00..T33 cx cy cz attach_ok ax ay az\n";
    std::map<uint, float> yaw_of_plant;
    for (const Site &s: sites) yaw_of_plant[s.plantID] = (s.yaw_rad > 0.f) ? s.yaw_rad : 0.f;
    size_t n_ped = 0, n_inf = 0;
    size_t bud_states[6] = {0, 0, 0, 0, 0, 0};   // every floral bud of a live shoot, by Helios BudState
    float worst_check_mm = 0.f;
    for (size_t k = 0; k < plantIDs.size(); k++) {
        const uint pid = plantIDs[k];
        const float yaw = yaw_of_plant.count(pid) ? yaw_of_plant[pid] : 0.f;
        const vec3 pbase = plantarchitecture.getPlantBasePosition(pid);
        const float cy = std::cos(yaw), sy = std::sin(yaw);
        auto turn = [&](const vec3 &v) {
            const vec3 a = v - pbase;
            return pbase + make_vec3(a.x * cy - a.y * sy, a.x * sy + a.y * cy, a.z);
        };
        for (uint shootID: plantarchitecture.getAllShootIDs(pid)) {
            if (plantarchitecture.isShootPruned(pid, shootID)) continue;
            const auto shoot = plantarchitecture.getPlantShoot(pid, shootID);
            for (size_t n = 0; n < shoot->phytomers.size(); n++) {
                const auto &phytomer = shoot->phytomers[n];
                for (const auto &petiole_buds: phytomer->floral_buds) {
                    for (const FloralBud &fb: petiole_buds) {
                        if (int(fb.state) >= 0 && int(fb.state) < 6) bud_states[int(fb.state)]++;
                        int ped_obj = -1;
                        for (uint objID: fb.peduncle_objIDs) {
                            if (!context.doesObjectExist(objID)) continue;
                            ped_obj = int(objID);
                            std::vector<vec3> line;
                            if (fb.parent_index < phytomer->peduncle_vertices.size() && fb.bud_index < phytomer->peduncle_vertices[fb.parent_index].size()) {
                                line = phytomer->peduncle_vertices[fb.parent_index][fb.bud_index];
                            }
                            float radius = 0.f;
                            if (fb.parent_index < phytomer->peduncle_radii.size() && fb.bud_index < phytomer->peduncle_radii[fb.parent_index].size() &&
                                !phytomer->peduncle_radii[fb.parent_index][fb.bud_index].empty()) {
                                radius = phytomer->peduncle_radii[fb.parent_index][fb.bud_index].front();
                            }
                            std::vector<vec3> verts;
                            for (uint UUID: context.getObjectPrimitiveUUIDs(objID)) {
                                const std::vector<vec3> v = context.getPrimitiveVertices(UUID);
                                verts.insert(verts.end(), v.begin(), v.end());
                            }
                            float check_mm = -1.f;
                            for (vec3 &p: line) {
                                p = turn(p);
                                float nearest = 1e9f;
                                for (const vec3 &v: verts) nearest = std::min(nearest, (v - p).magnitude());
                                if (nearest < 1e8f) check_mm = std::max(check_mm, nearest * 1000.f);
                            }
                            worst_check_mm = std::max(worst_check_mm, check_mm);
                            fd << "PED " << k << " " << shootID << " " << n << " " << fb.parent_index << " " << fb.bud_index << " " << int(fb.isterminal) << " " << int(fb.state)
                               << " " << objID << " " << radius << " " << line.size();
                            for (const vec3 &p: line) fd << " " << p.x << " " << p.y << " " << p.z;
                            fd << " " << check_mm << "\n";
                            n_ped++;
                        }
                        for (uint objID: fb.inflorescence_objIDs) {
                            if (!context.doesObjectExist(objID)) continue;
                            const char *kind = context.doesObjectDataExist(objID, "fruitID") ? "fruit"
                                             : context.doesObjectDataExist(objID, "openflowerID") ? "flower_open"
                                             : context.doesObjectDataExist(objID, "closedflowerID") ? "flower_closed"
                                             : (fb.state == BUD_FRUITING ? "fruit" : fb.state == BUD_FLOWER_OPEN ? "flower_open" : "flower_closed");
                            const int senescent = context.doesObjectDataExist(objID, "senescent_flower") ? 1 : 0;
                            size_t nv = 0;
                            vec3 vsum(0.f, 0.f, 0.f);
                            for (uint UUID: context.getObjectPrimitiveUUIDs(objID)) {
                                for (const vec3 &v: context.getPrimitiveVertices(UUID)) {
                                    vsum = vsum + v;
                                    nv++;
                                }
                            }
                            const vec3 centroid = nv ? vsum / float(nv) : vsum;
                            float T[16];
                            context.getObjectTransformationMatrix(objID, T);
                            // inflorescence_bases holds where this organ was attached (the peduncle point), turned by the yaw
                            vec3 attach(0.f, 0.f, 0.f);
                            int attach_ok = 0;
                            for (size_t q = 0; q < fb.inflorescence_objIDs.size() && q < fb.inflorescence_bases.size(); q++) {
                                if (fb.inflorescence_objIDs[q] == objID) {
                                    attach = turn(fb.inflorescence_bases[q]);
                                    attach_ok = 1;
                                }
                            }
                            fd << "INF " << k << " " << shootID << " " << n << " " << fb.parent_index << " " << fb.bud_index << " " << int(fb.isterminal) << " " << int(fb.state)
                               << " " << objID << " " << kind << " " << senescent << " " << ped_obj << " " << nv;
                            for (float t: T) fd << " " << t;
                            fd << " " << centroid.x << " " << centroid.y << " " << centroid.z << " " << attach_ok << " " << attach.x << " " << attach.y << " " << attach.z;
                            fd << "\n";
                            n_inf++;
                        }
                    }
                }
            }
        }
    }
    std::cout << "DIAG flowerdump flowerdump_peduncles=" << n_ped << " flowerdump_inflorescences=" << n_inf << " flowerdump_worst_check_mm=" << worst_check_mm
              << " flowerdump_bud_states=" << bud_states[0] << "," << bud_states[1] << "," << bud_states[2] << "," << bud_states[3]
              << "," << bud_states[4] << "," << bud_states[5] << " flowerdump_file=" << cfg.s("diag.flowerdump") << std::endl;
}

std::vector<uint> buildCanopy(const Config &cfg, Context &context, PlantArchitecture &plantarchitecture, unsigned scene_seed,
                              std::vector<Site> *sites_out = nullptr) {

    const vec2 bed_size(cfg.f("canopy.bed_size_x"), cfg.f("canopy.bed_size_y"));
    const vec2 plant_spacing(cfg.f("canopy.plant_spacing_x"), cfg.f("canopy.plant_spacing_y"));
    const bool library_defaults = configurePlantModel(cfg, plantarchitecture);
    const std::string species = plantSpecies(cfg);
    const bool cowpea = species == "cowpea";
    // Non-cowpea phenology: the library's own thresholds (set by build<Species>Plant) unless the config gives any
    // phenology.* key, in which case the missing ones default to the library's values, not to cowpea's.
    const bool phenology_keys = cfg.has("phenology.time_to_flower_initiation") || cfg.has("phenology.time_to_flower_opening") ||
                                cfg.has("phenology.time_to_fruit_set") || cfg.has("phenology.time_to_fruit_maturity") ||
                                cfg.has("phenology.time_to_dormancy");
    const std::vector<float> lib_phen = libraryPhenology(species);
    if (!cowpea && cfg.i("leaf.angle_tracking", 0) && !(cfg.has("leaf.angle_beta_mu") && cfg.has("leaf.angle_beta_nu"))) {
        helios_runtime_error("ERROR (buildCanopy): leaf.angle_tracking defaults to the measured cowpea Beta(1.398, 1.574); for canopy.species " +
                             species + " give leaf.angle_beta_mu and leaf.angle_beta_nu explicitly.");
    }

    // Row count was hard-coded at 2. Frame-level canopy cover is the gap being
    // closed here (synthetic 0.55 vs real 0.838), and row count is the lever that
    // raises cover WITHOUT advancing phenology -- canopy top height is already
    // pinned at 0.54 m by canopy.age and must not move.
    const int n_rows = cfg.i("canopy.rows", 2);
    const int2 max_plants(n_rows, int(std::floor(bed_size.y / plant_spacing.y)) + 1);
    // Germination fraction, drawn per scene. Two reasons it is a distribution and not a value.
    //
    // The cover response saturates: measured on the rasterized pass, cover runs 0.826 at germ 0.35,
    // 0.898 at 0.50, then flattens to 0.974 / 0.982 / 0.984 at 0.65 / 0.80 / 0.90. Past ~0.65 the
    // canopy is closed and further plants add nothing. The previous value of 0.90 sat deep in that
    // regime, which is why the synthetic set had no visible soil in any tile: its sparsest frame
    // was denser than 72% of the real ones.
    //
    // And the seed-to-seed spread collapses with it, from 0.13 at germ 0.35 to 0.011 at 0.65 --
    // germination is a stochastic per-plant draw, so a low fraction produces genuinely different
    // stands between scenes while a high one produces the same closed canopy every time. Sampling
    // the steep part of the curve therefore buys both the correct centre and the missing variety.
    const float germ_lo = cfg.f("canopy.germination_fraction_min", cfg.f("canopy.germination_fraction", 0.9f));
    const float germ_hi = cfg.f("canopy.germination_fraction_max", germ_lo);
    const float germ = (germ_hi > germ_lo) ? context.randu(germ_lo, germ_hi) : germ_lo;
    std::cout << "DIAG germination_fraction=" << germ << std::endl;

    // Per-site random streams (see Site above). Off by default so that every configuration
    // produced before this option existed still reproduces bit for bit from its scene seed.
    const bool per_plant_seed = cfg.i("canopy.per_plant_seed", 0) != 0;
    const float scene_age = cfg.f("canopy.age");

    // Where the plants stand. Either the bed grid with a germination draw per site (the
    // generation path), or an explicit layout written by the fitting code: one line per plant,
    //     x y yaw_deg age_days seed
    // in bed coordinates, so that plant positions measured in a real image can be imposed
    // directly and each site's plant is named by the seed of its own stream.
    const std::string layout_file = cfg.s("canopy.layout_file", "");
    std::vector<Site> sites;
    auto build_site = [&](Site &s) {
        if (per_plant_seed) {
            context.seedRandomGenerator(hashSeed(s.seed, 0));
        }
        s.plantID = plantarchitecture.buildPlantInstanceFromLibrary(s.position, 0);
        // The library's cowpea flowers at day 40 and only reaches realistic
        // flower density by ~day 75 -- by which point the canopy is 0.75 m
        // against a measured real 0.54 m. The model grows too tall relative
        // to when it flowers, so phenology is exposed and advanced to
        // reconcile the two: real cowpea IS flowering heavily at 0.54 m.
        if (!library_defaults && cowpea)
        plantarchitecture.setPlantPhenologicalThresholds(s.plantID,
                0.f,
                cfg.f("phenology.time_to_flower_initiation", 40.f),
                cfg.f("phenology.time_to_flower_opening", 5.f),
                cfg.f("phenology.time_to_fruit_set", 5.f),
                cfg.f("phenology.time_to_fruit_maturity", 30.f),
                cfg.f("phenology.time_to_dormancy", 1000.f));
        else if (!library_defaults && phenology_keys)
        plantarchitecture.setPlantPhenologicalThresholds(s.plantID,
                lib_phen[0],
                cfg.f("phenology.time_to_flower_initiation", lib_phen[1]),
                cfg.f("phenology.time_to_flower_opening", lib_phen[2]),
                cfg.f("phenology.time_to_fruit_set", lib_phen[3]),
                cfg.f("phenology.time_to_fruit_maturity", lib_phen[4]),
                cfg.f("phenology.time_to_dormancy", lib_phen[5]));
        // Leaf inclination steered through growth rather than imposed on the finished plant. Measured cowpea runs
        // Beta(1.398, 1.574) -- mean inclination 42 degrees -- consistently across many genotypes, where the library
        // generates a flatter canopy; and re-aiming a grown plant (leaf.set_angle_distribution) moves leaves that have
        // already been placed, so the canopy shifts between timesteps and a leaf's final angle depends on when the
        // distribution was applied. Tracking gives each leaf a target as it emerges and turns it onto that target while
        // it expands, so the plant matches the distribution at every age and a grown leaf is never moved again.
        // leaf.angle_tracking_lambda trades filling the distribution against keeping the angle the model generated:
        // 0 leaves the plant untouched, order 180 matches as closely as the growing plant allows.
        if (cfg.i("leaf.angle_tracking", 0)) {
            plantarchitecture.enablePlantLeafElevationAngleDistributionTracking(s.plantID,
                    cfg.f("leaf.angle_beta_mu", 1.398f), cfg.f("leaf.angle_beta_nu", 1.574f),
                    cfg.f("leaf.angle_tracking_lambda", 180.f));
        }
    };
    if (!layout_file.empty()) {
        std::ifstream f(layout_file);
        if (!f) {
            helios_runtime_error("ERROR (buildCanopy): cannot open canopy.layout_file " + layout_file);
        }
        std::string line;
        while (std::getline(f, line)) {
            const size_t c = line.find('#');
            if (c != std::string::npos) line = line.substr(0, c);
            std::istringstream ss(line);
            Site s;
            float yaw_deg = 0.f;
            if (!(ss >> s.position.x >> s.position.y >> yaw_deg >> s.age_days >> s.seed)) continue;
            s.position.z = 0.01f;
            s.yaw_rad = deg2rad(yaw_deg);
            if (s.age_days <= 0.f) {
                helios_runtime_error("ERROR (buildCanopy): canopy.layout_file line '" + line + "' has a non-positive age.");
            }
            build_site(s);
            sites.push_back(s);
        }
        std::cout << "DIAG layout_file=" << layout_file << " sites=" << sites.size() << std::endl;
    } else {
        // Presence, seed and yaw are all functions of the site index in per-plant mode, so the
        // stand at every other site is unchanged when one site is re-drawn. The legacy path draws
        // presence from the shared stream between plant builds, and yaw after growth, exactly as
        // it always did.
        for (int j = 0; j < max_plants.y; j++) {
            for (int i = 0; i < max_plants.x; i++) {
                const unsigned k = unsigned(j * max_plants.x + i);
                const unsigned site_seed = hashSeed(hashSeed(scene_seed, 101) + k, 102);
                const bool present = per_plant_seed ? (hashUniform(site_seed, 3) < germ) : (context.randu() < germ);
                if (!present) continue;
                Site s;
                s.position = make_vec3(-0.5f * (n_rows - 1) * plant_spacing.x + i * plant_spacing.x,
                                       -bed_size.y / 2.f + j * plant_spacing.y, 0.01f);
                s.seed = site_seed;
                s.age_days = scene_age;
                if (per_plant_seed) {
                    s.yaw_rad = cfg.i("canopy.random_plant_yaw", 1) ? 2.f * float(M_PI) * hashUniform(site_seed, 4) : 0.f;
                }
                build_site(s);
                sites.push_back(s);
            }
        }
    }
    std::vector<uint> plantIDs;
    plantIDs.reserve(sites.size());
    for (const Site &s: sites) plantIDs.push_back(s.plantID);
    std::cout << "built " << plantIDs.size() << " " << species << " plants" << std::endl;

    // --- nitrogen model, for leaf-to-leaf colour variation ---------------------------------
    // Every leaf in this scene was rendered with one spectrum: leafoptics.run() was called once
    // over getAllLeafUUIDs() with a single chlorophyll value, so the canopy is uniformly green in
    // a way the real one is not. Measured on leaf-sized windows, real foliage spans 9.0 units of
    // CIELAB a* between its 10th and 90th percentiles and the synthetic set spans 4.0 -- and the
    // missing half is the DARK end, a* -28 against a synthetic floor of -23.
    //
    // PlantArchitecture's nitrogen model produces that spread physically rather than by jitter.
    // New leaves start empty and fill toward target_leaf_N_area at a capped rate, so young leaves
    // are genuinely nitrogen-poor and therefore paler, while mature leaves sit at target and are
    // darkest; past remobilization_age_threshold the oldest leaves give nitrogen back to the
    // growing points and pale again. LeafOptics reads the per-leaf "leaf_nitrogen_gN_m2" object
    // data the model writes and bins it into distinct PROSPECT spectra.
    if (cfg.i("leaf.nitrogen_model", 0)) {
        NitrogenParameters nitrogen;
        nitrogen.target_leaf_N_area = cfg.f("leaf.target_N_area", 2.6f);
        nitrogen.minimum_leaf_N_area = cfg.f("leaf.minimum_N_area", 0.8f);
        nitrogen.root_allocation_fraction = cfg.f("leaf.root_N_allocation", 0.15f);
        nitrogen.max_N_accumulation_rate = cfg.f("leaf.max_N_accumulation_rate", 0.1f);
        nitrogen.leaf_remobilization_efficiency = cfg.f("leaf.remobilization_efficiency", 0.70f);
        nitrogen.remobilization_age_threshold = cfg.f("leaf.remobilization_age_threshold", 0.70f);
        plantarchitecture.enableNitrogenModel();
        plantarchitecture.setPlantNitrogenParameters(plantIDs, nitrogen);
        plantarchitecture.initializeNitrogenPools(cfg.f("leaf.initial_N_area", 1.0f));
        // Leaves can only draw from the available pool, so without a supply every leaf stays at
        // its initial value and the model produces no variation at all.
        plantarchitecture.addPlantNitrogen(plantIDs, cfg.f("leaf.nitrogen_supply_gN", 1.0f));
    }

    if (per_plant_seed || !layout_file.empty()) {
        // One plant at a time, each from its own reseeded stream, so that plant k's growth
        // consumes no random values that any other plant's growth depends on. Growing them
        // together would interleave the plants' draws step by step and re-couple them.
        plantarchitecture.disableMessages();
        for (const Site &s: sites) {
            if (per_plant_seed) {
                context.seedRandomGenerator(hashSeed(s.seed, 1));
            }
            plantarchitecture.advanceTime(s.plantID, s.age_days);
        }
        plantarchitecture.enableMessages();
    } else {
        plantarchitecture.advanceTime(cfg.i("canopy.age"));
    }

    // Plant height is a measured constraint (0.54 m) that node count and internode length can each
    // break, so it is reported rather than assumed whenever either is changed.
    {
        std::vector<float> heights;
        heights.reserve(plantIDs.size());
        for (uint pid: plantIDs) {
            heights.push_back(plantarchitecture.getPlantHeight(pid));
        }
        if (!heights.empty()) {
            std::sort(heights.begin(), heights.end());
            std::cout << "DIAG plant_height median=" << heights[heights.size() / 2]
                      << " p90=" << heights[size_t(0.9 * float(heights.size() - 1))]
                      << " measured_real=0.54" << std::endl;
        }
    }

    // How much nitrogen the canopy would need to fill every leaf to target, against what was
    // supplied. Leaves draw from a per-plant available pool, so if the supply is short of the
    // demand no leaf reaches its target and neither target_N_area nor max_N_accumulation_rate has
    // any effect -- a sweep over those two then reports the same rate-limited canopy at every point,
    // which is exactly what the first two calibration grids did.
    if (cfg.i("leaf.nitrogen_model", 0)) {
        const std::vector<uint> leaf_uuids = plantarchitecture.getAllLeafUUIDs();

        // Enforce the minimum leaf nitrogen. PlantArchitecture initialises leaves created DURING
        // growth at zero -- initializeNitrogenPools only seeds the leaves that exist when it is
        // called -- so the youngest leaves would carry zero chlorophyll and render white-yellow. A
        // real emerging leaf carries a baseline chlorophyll complement and is never at zero:
        // measured through this camera, leaf hue falls to 115 deg below Cab 20, while every real
        // leaf patch including the palest sits at 123 deg, which is Cab 50 and above.
        //
        // This lives in buildCanopy, not in the render path, for two reasons: the geom pass shares
        // this function and would otherwise calibrate against an unclamped canopy, and the DIAG
        // below must report the distribution that is actually rendered rather than the one before
        // the clamp.
        const float floor_N = cfg.f("leaf.minimum_N_area", 0.8f);
        uint raised = 0;
        for (uint uuid: leaf_uuids) {
            const uint objID = context.getPrimitiveParentObjectID(uuid);
            if (objID > 0 && context.doesObjectDataExist(objID, "leaf_nitrogen_gN_m2")) {
                float leaf_N = 0.f;
                context.getObjectData(objID, "leaf_nitrogen_gN_m2", leaf_N);
                if (leaf_N < floor_N) {
                    context.setObjectData(objID, "leaf_nitrogen_gN_m2", floor_N);
                    raised++;
                }
            }
        }
        // Leaf elevation angle. Measured at mean 48 deg, which is close to a spherical (randomly
        // oriented) canopy. Cowpea is planophile -- broad, roughly horizontal leaves, mean
        // inclination nearer 30 deg -- and the difference is a projection factor of
        // cos(30)/cos(48) = 1.29 in a nadir view, which is larger than the 1.17x apparent-leaf-size
        // gap that three rounds of raising leaf.prototype_scale failed to close.
        //
        // The Beta parameters are calibrated by measurement rather than taken from a convention:
        // scripts/incl_beta_sweep.sh varies them and reads the mean back from the DIAG below.
        std::cout << "DIAG nitrogen_floor value=" << floor_N << " primitives_raised=" << raised << std::endl;

        float leaf_area = 0.f;
        for (uint uuid: leaf_uuids) {
            leaf_area += context.getPrimitiveArea(uuid);
        }
        const float demand_gN = leaf_area * cfg.f("leaf.target_N_area", 2.6f);
        const float supplied_gN = float(plantIDs.size()) * cfg.f("leaf.nitrogen_supply_gN", 1.0f)
                                  * (1.f - cfg.f("leaf.root_N_allocation", 0.15f));
        std::cout << "DIAG nitrogen leaf_area_m2=" << leaf_area
                  << " demand_gN=" << demand_gN
                  << " supplied_to_leaves_gN=" << supplied_gN
                  << " supply_ratio=" << supplied_gN / std::max(demand_gN, 1e-6f) << std::endl;

        // The achieved per-leaf nitrogen, read back from the object data the model publishes.
        // Colour is three transformations downstream of this (N -> Cab -> PROSPECT spectrum ->
        // rendered pixel), so diagnosing the model from rendered a* means guessing which stage
        // failed. Read the state directly instead.
        std::vector<float> leaf_N;
        std::set<uint> leaf_objects;
        for (uint uuid: leaf_uuids) {
            const uint objID = context.getPrimitiveParentObjectID(uuid);
            if (objID > 0 && context.doesObjectDataExist(objID, "leaf_nitrogen_gN_m2")) {
                leaf_objects.insert(objID);
            }
        }
        for (uint objID: leaf_objects) {
            float value = 0.f;
            context.getObjectData(objID, "leaf_nitrogen_gN_m2", value);
            leaf_N.push_back(value);
        }
        if (leaf_N.empty()) {
            helios_runtime_error("ERROR (buildCanopy): the nitrogen model is enabled but no leaf "
                                 "object carries 'leaf_nitrogen_gN_m2'. Either the model did not "
                                 "run during advanceTime, or the leaf objects were rebuilt after "
                                 "it did, and every leaf will render with the same spectrum.");
        }
        std::sort(leaf_N.begin(), leaf_N.end());
        auto pct = [&](float q) { return leaf_N[size_t(q * float(leaf_N.size() - 1))]; };
        const float mean_N = std::accumulate(leaf_N.begin(), leaf_N.end(), 0.f) / float(leaf_N.size());
        const float cab = 100.f * cfg.f("leaf.f_photosynthetic", 0.50f) * cfg.f("leaf.N_to_Cab_coefficient", 0.40f);
        // p10 and p90 are reported because the leaf-colour metric compares exactly those
        // percentiles; anything else would need converting before the two could be compared.
        std::cout << "DIAG leafN n=" << leaf_N.size()
                  << " N_p50=" << pct(0.50f) << " N_mean=" << mean_N
                  << " target=" << cfg.f("leaf.target_N_area", 2.6f)
                  << " Cab_p10=" << pct(0.10f) * cab << " Cab_p25=" << pct(0.25f) * cab
                  << " Cab_p50=" << pct(0.50f) * cab << " Cab_p75=" << pct(0.75f) * cab
                  << " Cab_p90=" << pct(0.90f) * cab
                  << " Cab_spread=" << (pct(0.90f) - pct(0.10f)) * cab
                  << " uniform_Cab=" << cfg.f("leaf.chlorophyll") << std::endl;
    }

    assignLeafChlorophyll(cfg, context, plantarchitecture, plantIDs, sites);

    // Leaf angle distribution and its measurement, for any configuration (this used to sit inside
    // the nitrogen block and was silently skipped whenever that model was off).
    // diag.leafdir 1: each leaflet's base and the azimuth/elevation of its base-to-farthest-vertex direction, before and
    // after the angle distribution is imposed, to check the leaflets stay pointing along their petioles.
    auto print_leaf_directions = [&](const char *stage) {
        if (!cfg.i("diag.leafdir", 0)) return;
        const uint pid = plantIDs.front();
        const std::vector<uint> leaves = plantarchitecture.getPlantLeafObjectIDs(pid);
        const std::vector<vec3> bases = plantarchitecture.getPlantLeafBases(pid);
        for (size_t i = 0; i < leaves.size() && i < bases.size(); i++) {
            vec3 far = bases[i];
            float far_d = 0;
            for (uint UUID: context.getObjectPrimitiveUUIDs(leaves[i])) {
                for (const vec3 &v: context.getPrimitiveVertices(UUID)) {
                    if ((v - bases[i]).magnitude() > far_d) { far_d = (v - bases[i]).magnitude(); far = v; }
                }
            }
            const vec3 d = far - bases[i];
            std::cout << "LEAFDIR " << stage << " " << leaves[i] << " base " << bases[i].x << " " << bases[i].y << " " << bases[i].z
                      << " az " << rad2deg(std::atan2(d.y, d.x)) << " elev " << rad2deg(std::atan2(d.z, std::sqrt(d.x * d.x + d.y * d.y)))
                      << " len " << far_d << std::endl;
        }
    };
    print_leaf_directions("before");
    if (cfg.i("leaf.set_angle_distribution", 0) && cfg.i("leaf.angle_tracking", 0)) {
        helios_runtime_error("ERROR (buildCanopy): leaf.set_angle_distribution re-aims the finished plant and "
                             "leaf.angle_tracking steers it through growth; enabling both would impose the distribution "
                             "twice, the second pass undoing the arrangement the first produced. Use one.");
    }
    if (cfg.i("leaf.set_angle_distribution", 0)) {
        // The inclinations are drawn from the Context's own generator (sample_Beta_distribution in
        // PlantArchitecture), whose state depends on everything that drew from it earlier in the run. That differs
        // between the rasterizer and the ray tracer, so the same layout and the same per-plant seeds were producing
        // different leaf poses in the fit and in the render -- per-plant silhouette IoU between the two was 0.20-0.29.
        // Seeding here makes the draw depend on nothing but this config, so the canopy the fit scores is the canopy
        // that gets rendered. canopy.per_plant_seed keeps the rest of the plant reproducible; this covers the poses.
        context.seedRandomGenerator(uint(cfg.i("leaf.angle_seed", 20250918)));
        plantarchitecture.setPlantLeafElevationAngleDistribution(
                plantIDs, cfg.f("leaf.angle_beta_mu", 1.0f), cfg.f("leaf.angle_beta_nu", 1.0f));
    }
    print_leaf_directions("after");

    // diag.dump_prefix <path>: the first plant's leaves, petioles and internodes as OBJ files, after the angle distribution.
    if (cfg.has("diag.dump_prefix")) {
        const uint pid = plantIDs.front();
        context.writeOBJ(cfg.s("diag.dump_prefix") + "_leaves.obj", context.getObjectPrimitiveUUIDs(plantarchitecture.getPlantLeafObjectIDs(pid)), false, true);
        context.writeOBJ(cfg.s("diag.dump_prefix") + "_petioles.obj", context.getObjectPrimitiveUUIDs(plantarchitecture.getPlantPetioleObjectIDs(pid)), false, true);
        context.writeOBJ(cfg.s("diag.dump_prefix") + "_internodes.obj", context.getObjectPrimitiveUUIDs(plantarchitecture.getPlantInternodeObjectIDs(pid)), false, true);
    }

    // Leaf inclination. A leaf inclined at theta from horizontal projects cos(theta) of its
    // length into a nadir view, so an over-steep canopy renders leaves that measure small
    // however large they actually are -- which is what three rounds of raising
    // leaf.prototype_scale failed to fix: apparent leaf size moved 52->65 px for a 1.96x scale
    // increase, while real leaves measure 75.9.
    {
        const std::vector<float> hist = plantarchitecture.getPlantLeafInclinationAngleDistribution(plantIDs, 9, true);
        float mean_angle = 0.f, total = 0.f;
        for (size_t b = 0; b < hist.size(); b++) {
            const float centre = (float(b) + 0.5f) * 90.f / float(hist.size());
            mean_angle += centre * hist[b];
            total += hist[b];
        }
        if (total > 0.f) mean_angle /= total;
        std::cout << "DIAG leaf_inclination mean_deg=" << mean_angle
                  << " projection_factor=" << std::cos(mean_angle * float(M_PI) / 180.f) << " hist=";
        for (float h: hist) std::cout << h << ",";
        std::cout << std::endl;
    }


    // diag.write_plant_xml <prefix>: every site's plant as a plant-structure XML (<prefix>_s<k>.xml), written here because the
    // per-plant yaw below turns the geometry without touching the plant's own state, which is what the XML records; and a
    // canopy.plant_xml list (<prefix>_list.txt, after the yaw is known) that puts each plant back at its yaw and seed.
    const std::string xml_prefix = cfg.s("diag.write_plant_xml", "");
    for (size_t k = 0; k < sites.size() && !xml_prefix.empty(); k++) {
        plantarchitecture.writePlantStructureXML(sites[k].plantID, xml_prefix + "_s" + std::to_string(k) + ".xml");
    }

    // Give each plant a random azimuth about its own base. Nothing in the library randomizes a
    // plant's overall orientation -- ShootParameters::base_yaw is a per-shoot branching angle, and
    // the cowpea model draws it from only +/-20 deg -- so every plant in the plot faces within a
    // narrow wedge of the same direction. Measured on the rendered annotations, 92% of open-flower
    // boxes came out taller than wide, against a real 46%: at nadir with no preferred azimuth the
    // split must be even. The anisotropy also inflates apparent elongation, because an axis-aligned
    // elongated object fills its bounding box while a diagonal one does not.
    //
    // Applied after advanceTime() so it rotates finished geometry; the plants are not grown again.
    //
    // A site that carries its own yaw (per-plant mode, or a layout file) is turned by that; the
    // legacy path draws from the shared stream here, after growth, as it always has.
    for (Site &s: sites) {
        if (s.yaw_rad < 0.f) {
            if (!cfg.i("canopy.random_plant_yaw", 1)) continue;
            s.yaw_rad = context.randu(0.f, 2.f * float(M_PI));
        }
        const std::vector<uint> uuids = plantarchitecture.getAllPlantUUIDs(s.plantID);
        if (uuids.empty() || s.yaw_rad == 0.f) continue;
        const vec3 base = plantarchitecture.getPlantBasePosition(s.plantID);
        if (cfg.i("diag.yawcoverage", 0)) {
            std::set<uint> in_uuids(uuids.begin(), uuids.end());
            size_t organ_primitives = 0, covered = 0;
            auto count = [&](const std::vector<uint> &objIDs) {
                for (uint objID: objIDs) {
                    if (!context.doesObjectExist(objID)) continue;
                    for (uint u: context.getObjectPrimitiveUUIDs(objID)) {
                        organ_primitives++;
                        if (in_uuids.count(u)) covered++;
                    }
                }
            };
            count(plantarchitecture.getPlantLeafObjectIDs(s.plantID));
            const size_t leaf_primitives = organ_primitives, leaf_covered = covered;
            count(plantarchitecture.getPlantPetioleObjectIDs(s.plantID));
            count(plantarchitecture.getPlantInternodeObjectIDs(s.plantID));
            std::cout << "DIAG yawcoverage plant=" << s.plantID << " plant_uuids=" << uuids.size()
                      << " leaf_primitives=" << leaf_primitives << " leaf_covered=" << leaf_covered
                      << " organ_primitives=" << organ_primitives << " organ_covered=" << covered << std::endl;
        }
        // A petiole vertex, watched across the rotation. Rotating the wrong way -- primitives instead of objects --
        // moves the leaves and silently leaves every stalk behind, which is invisible in any aggregate and shows up
        // only as plants whose petioles point away from their own leaves. Checked on every run, one vertex per plant.
        vec3 probe_before(0, 0, 0), probe_after(0, 0, 0);
        uint probe_uuid = 0;
        for (uint objID: plantarchitecture.getPlantPetioleObjectIDs(s.plantID)) {
            if (!context.doesObjectExist(objID)) continue;
            const std::vector<uint> prims = context.getObjectPrimitiveUUIDs(objID);
            if (prims.empty()) continue;
            probe_uuid = prims.front();
            probe_before = context.getPrimitiveVertices(probe_uuid).front();
            break;
        }
        // Rotate the plant's OBJECTS, not its primitives. Context::rotatePrimitive() applies the transform to each
        // primitive it is handed, which moves a leaf (a patch or polymesh) but does nothing at all to a petiole or an
        // internode: those are tube objects, and Primitive::applyTransform() refuses to transform a primitive that
        // belongs to a compound object. It says so -- "Cannot transform individual primitives within a compound
        // object" -- but the warning goes to stdout among thousands of lines that every caller here filters down to
        // its DIAG lines, so it was never seen. The plant's leaves swung round its base while every stalk stayed put,
        // which is what rendered as petioles with no leaves on them and what the fits scored for months.
        const std::vector<uint> plant_objects = plantarchitecture.getAllPlantObjectIDs(s.plantID);
        context.rotateObject(plant_objects, s.yaw_rad, base, make_vec3(0, 0, 1));
        // Anything of this plant that is a loose primitive rather than part of an object still needs the primitive
        // call; rotating it twice would be worse than not rotating it, so those are the ones the objects do not cover.
        std::set<uint> object_primitives;
        for (uint objID: plant_objects) {
            if (!context.doesObjectExist(objID)) continue;
            for (uint u: context.getObjectPrimitiveUUIDs(objID)) object_primitives.insert(u);
        }
        std::vector<uint> loose;
        for (uint u: uuids) {
            if (!object_primitives.count(u)) loose.push_back(u);
        }
        if (!loose.empty()) {
            context.rotatePrimitive(loose, s.yaw_rad, base, make_vec3(0, 0, 1));
        }
        if (probe_uuid != 0) {
            probe_after = context.getPrimitiveVertices(probe_uuid).front();
            // Where the rotation should have put it, computed independently of how it was applied.
            const vec3 arm = probe_before - base;
            const vec3 expected = base + make_vec3(arm.x * std::cos(s.yaw_rad) - arm.y * std::sin(s.yaw_rad),
                                                   arm.x * std::sin(s.yaw_rad) + arm.y * std::cos(s.yaw_rad), arm.z);
            const float error_mm = (probe_after - expected).magnitude() * 1000.f;
            if (error_mm > 1.f) {
                helios_runtime_error("ERROR (buildCanopy): the per-plant yaw rotation did not move plant " + std::to_string(s.plantID) +
                                     "'s petiole geometry: a probe vertex is " + std::to_string(error_mm) +
                                     " mm from where a rotation of " + std::to_string(rad2deg(s.yaw_rad)) +
                                     " degrees about the plant base should have put it. Tube organs (petioles, internodes) move only "
                                     "through Context::rotateObject(); a primitive-level transform on them is discarded, which leaves "
                                     "every stalk behind while the leaves turn.");
            }
            if (cfg.i("diag.yawcoverage", 0)) {
                std::cout << "DIAG yawprobe plant=" << s.plantID << " yaw_deg=" << rad2deg(s.yaw_rad)
                          << " moved_mm=" << (probe_after - probe_before).magnitude() * 1000.f << " error_mm=" << error_mm << std::endl;
            }
        }
    }
    if (!xml_prefix.empty()) {
        std::ofstream list(xml_prefix + "_list.txt");
        list << "# path yaw_deg seed\n";
        for (size_t k = 0; k < sites.size(); k++) {
            list << xml_prefix << "_s" << k << ".xml " << std::setprecision(9) << rad2deg(std::max(sites[k].yaw_rad, 0.f)) << " " << sites[k].seed << "\n";
        }
        std::cout << "DIAG write_plant_xml plants=" << sites.size() << " list=" << xml_prefix << "_list.txt" << std::endl;
    }
    // These diagnostics describe finished geometry, so they sit after the per-plant yaw rotation above: run
    // before it they reported each plant's leaves in its pre-rotation frame, which matches nothing that is
    // drawn or rendered. Relative measurements within a plant (a leaflet against its own petiole) are
    // unaffected by that rotation, but every position and every projection into the image was.
    // diag.leafruler <path>: every leaflet in the scene as the four world points a hand label clicks -- the
    // attachment base, the vertex farthest from it along the midrib (the tip), and the two vertices farthest
    // to either side of that axis. Projected through the camera by scripts/twin_ruler.py these give each
    // leaflet's apparent length and width whether or not it is occluded, which a connected-component
    // measurement on the rendered image cannot: there a leaflet half hidden behind another one reads short,
    // and it reads shortest in exactly the canopies that are densest, so comparing a dense twin against a
    // sparse real canopy that way reports the twin's leaves smaller however large they are. Hand labels of
    // the 06-20 Plot286 twin measured 61.8 mm where that method reported 46 mm.
    //
    // Object IDs and bases are paired by index as in print_leaf_directions above.
    dumpLeafTransforms(cfg, context, plantarchitecture, plantIDs);
    dumpLeafVertices(cfg, context, plantarchitecture, plantIDs);
    dumpLeafUVFit(cfg, context, plantarchitecture, plantIDs);
    if (cfg.has("diag.leafruler")) {
        const std::string ruler_path = cfg.s("diag.leafruler");
        std::ofstream ruler(ruler_path);
        if (!ruler) {
            helios_runtime_error("ERROR: cannot open diag.leafruler file " + ruler_path + " for writing.");
        }
        ruler << "# plant objID base_offset_mm base_x base_y base_z tip_x tip_y tip_z w1_x w1_y w1_z w2_x w2_y w2_z\n";
        size_t leaflets_written = 0;
        for (size_t p = 0; p < plantIDs.size(); p++) {
            const std::vector<uint> leaves = plantarchitecture.getPlantLeafObjectIDs(plantIDs[p]);
            const std::vector<vec3> bases = plantarchitecture.getPlantLeafBases(plantIDs[p]);
            for (size_t i = 0; i < leaves.size() && i < bases.size(); i++) {
                // Blade facets only. A leaf object also carries its petiolule -- the short stalk joining the leaflet to
                // the rachis -- and including it measured the blade plus its stalk: the population median came out at
                // 111 mm projected where the blade prototype itself is at most 104 mm, which is how the error showed.
                // Helios labels the two, so the stalk is dropped here; a leaf whose primitives carry no label at all is
                // a simple leaf with no petiolule, and all of its facets are blade.
                std::vector<vec3> vertices;
                for (uint UUID: context.getObjectPrimitiveUUIDs(leaves[i])) {
                    if (context.doesPrimitiveDataExist(UUID, "object_label")) {
                        std::string primitive_label;
                        context.getPrimitiveData(UUID, "object_label", primitive_label);
                        if (primitive_label == "petiolule") {
                            continue;
                        }
                    }
                    const std::vector<vec3> primitive_vertices = context.getPrimitiveVertices(UUID);
                    vertices.insert(vertices.end(), primitive_vertices.begin(), primitive_vertices.end());
                }
                if (vertices.empty()) {
                    continue;
                }
                // The blade's own longest chord, taken from its geometry alone. getPlantLeafBases() reports the
                // attachment position the plant recorded when the leaf was built, and the per-plant yaw applied after
                // growth moves the geometry without updating it -- by a median of 39 mm and as much as 178 mm here --
                // so measuring from that base spans a stale point to a rotated blade and reads far too long: the
                // population median came out at 112 mm where the blade prototype is at most 104. Two passes give the
                // extremes of the point set: the vertex farthest from the centroid, then the vertex farthest from it.
                vec3 centroid(0.f, 0.f, 0.f);
                for (const vec3 &v: vertices) centroid = centroid + v;
                centroid = centroid / float(vertices.size());
                vec3 base = vertices.front();
                float far_from_centroid = -1.f;
                for (const vec3 &v: vertices) {
                    if ((v - centroid).magnitude() > far_from_centroid) {
                        far_from_centroid = (v - centroid).magnitude();
                        base = v;
                    }
                }
                const float base_offset = (base - bases[i]).magnitude() * 1000.f;   // reported, no longer relied upon
                vec3 tip = base;
                float tip_distance = 0.f;
                for (const vec3 &v: vertices) {
                    if ((v - base).magnitude() > tip_distance) {
                        tip_distance = (v - base).magnitude();
                        tip = v;
                    }
                }
                if (tip_distance < 1e-6f) {
                    continue;
                }
                const vec3 midrib = (tip - base).normalize();
                // Width across the midrib at its widest station, not the two vertices farthest from the
                // axis: on a folded or oblique leaflet those two sit at different distances along the
                // midrib and span a diagonal, which measured 20% wider than a hand label of the same leaf.
                vec3 across = base;
                float across_offset = 0.f;
                for (const vec3 &v: vertices) {
                    const vec3 offset = (v - base) - midrib * ((v - base) * midrib);
                    if (offset.magnitude() > across_offset) {
                        across_offset = offset.magnitude();
                        across = offset;
                    }
                }
                vec3 widest_one = base, widest_other = base;
                if (across_offset > 1e-9f) {
                    const vec3 across_hat = across.normalize();
                    const size_t n_stations = 20;
                    std::vector<vec3> station_max(n_stations, base), station_min(n_stations, base);
                    std::vector<float> offset_max(n_stations, 0.f), offset_min(n_stations, 0.f);
                    for (const vec3 &v: vertices) {
                        const float along = std::clamp(((v - base) * midrib) / tip_distance, 0.f, 0.999f);
                        const size_t station = size_t(along * float(n_stations));
                        const float offset = (v - base) * across_hat;
                        if (offset > offset_max[station]) {
                            offset_max[station] = offset;
                            station_max[station] = v;
                        }
                        if (offset < offset_min[station]) {
                            offset_min[station] = offset;
                            station_min[station] = v;
                        }
                    }
                    float widest = 0.f;
                    for (size_t station = 0; station < n_stations; station++) {
                        if (offset_max[station] - offset_min[station] > widest) {
                            widest = offset_max[station] - offset_min[station];
                            widest_one = station_max[station];
                            widest_other = station_min[station];
                        }
                    }
                }
                ruler << p << " " << leaves[i] << " " << base_offset << " " << base.x << " " << base.y << " " << base.z << " " << tip.x << " " << tip.y << " " << tip.z << " " << widest_one.x << " " << widest_one.y << " "
                      << widest_one.z << " " << widest_other.x << " " << widest_other.y << " " << widest_other.z << "\n";
                leaflets_written++;
            }
        }
        std::cout << "DIAG leafruler leaflets=" << leaflets_written << " file=" << ruler_path << std::endl;
    }

    // diag.stalkdump <path>: the two ends of every petiole, internode and peduncle in the scene, so that the bare
    // stalks in a render can be attributed to an organ type by overlaying them on the image (scripts/twin_stalks.py).
    // Ends are approximated as the vertex farthest from the object's centroid and the vertex farthest from that one,
    // which is the tube's long axis for the tapered tubes these organs are built from.
    if (cfg.has("diag.stalkdump")) {
        std::ofstream stalks(cfg.s("diag.stalkdump"));
        if (!stalks) {
            helios_runtime_error("ERROR: cannot open diag.stalkdump file " + cfg.s("diag.stalkdump") + " for writing.");
        }
        // Straightness as well as the ends. A real cowpea petiole is a bow, not a rod, and a bowed one reaches a
        // shorter distance than its own length -- so an end-to-end measurement of a straight model petiole is not
        // comparable to a hand label spanning a curved real one, and a bowed petiole sets its leaf down closer to the
        // stem and lower, which is the difference between a ring of leaves and a filled disc.
        //   arc_mm    the length of the centerline, which is what the organ has grown
        //   chord_mm  the distance between its ends, which is what a label or a projection measures
        //   sag_mm    the greatest departure of the centerline from that chord: zero for a rod
        stalks << "# type plant objID x1 y1 z1 x2 y2 z2 arc_mm chord_mm sag_mm\n";
        for (size_t k = 0; k < plantIDs.size(); k++) {
            const std::vector<std::pair<const char *, std::vector<uint>>> organs = {
                    {"petiole", plantarchitecture.getPlantPetioleObjectIDs(plantIDs[k])},
                    {"internode", plantarchitecture.getPlantInternodeObjectIDs(plantIDs[k])},
                    {"peduncle", plantarchitecture.getPlantPeduncleObjectIDs(plantIDs[k])}};
            for (const auto &organ: organs) {
                for (uint objID: organ.second) {
                    if (!context.doesObjectExist(objID)) continue;
                    std::vector<vec3> vertices;
                    for (uint UUID: context.getObjectPrimitiveUUIDs(objID)) {
                        const std::vector<vec3> v = context.getPrimitiveVertices(UUID);
                        vertices.insert(vertices.end(), v.begin(), v.end());
                    }
                    if (vertices.size() < 2) continue;
                    vec3 centroid(0.f, 0.f, 0.f);
                    for (const vec3 &v: vertices) centroid = centroid + v;
                    centroid = centroid / float(vertices.size());
                    vec3 end_one = vertices.front(), end_two = vertices.front();
                    float farthest = -1.f;
                    for (const vec3 &v: vertices) {
                        if ((v - centroid).magnitude() > farthest) {
                            farthest = (v - centroid).magnitude();
                            end_one = v;
                        }
                    }
                    farthest = -1.f;
                    for (const vec3 &v: vertices) {
                        if ((v - end_one).magnitude() > farthest) {
                            farthest = (v - end_one).magnitude();
                            end_two = v;
                        }
                    }
                    // The centerline, recovered by averaging the tube's ring of vertices at each station along the
                    // chord: the rings are what give the tube its radius, and taking raw vertex offsets would report
                    // that radius as curvature.
                    const vec3 chord = end_two - end_one;
                    const float chord_length = chord.magnitude();
                    float arc_mm = chord_length * 1000.f, sag_mm = 0.f;
                    if (chord_length > 1e-6f) {
                        const vec3 chord_hat = chord / chord_length;
                        const size_t n_stations = 12;
                        std::vector<vec3> station_sum(n_stations, make_vec3(0.f, 0.f, 0.f));
                        std::vector<size_t> station_count(n_stations, 0);
                        for (const vec3 &v: vertices) {
                            const float along = std::clamp(((v - end_one) * chord_hat) / chord_length, 0.f, 0.999f);
                            const size_t station = size_t(along * float(n_stations));
                            station_sum[station] = station_sum[station] + v;
                            station_count[station]++;
                        }
                        std::vector<vec3> centerline;
                        for (size_t station = 0; station < n_stations; station++) {
                            if (station_count[station] > 0) centerline.push_back(station_sum[station] / float(station_count[station]));
                        }
                        float arc = 0.f;
                        for (size_t i = 1; i < centerline.size(); i++) arc += (centerline[i] - centerline[i - 1]).magnitude();
                        for (const vec3 &c: centerline) {
                            const vec3 offset = (c - end_one) - chord_hat * ((c - end_one) * chord_hat);
                            sag_mm = std::max(sag_mm, offset.magnitude() * 1000.f);
                        }
                        // The centerline runs between station centres, not between the ends, so it is short by the two
                        // half-stations at either end; scale it onto the chord's own span to compare like with like.
                        if (centerline.size() > 1) {
                            const float spanned = (centerline.back() - centerline.front()).magnitude();
                            arc_mm = (spanned > 1e-6f) ? arc * chord_length / spanned * 1000.f : chord_length * 1000.f;
                        }
                    }
                    stalks << organ.first << " " << k << " " << objID << " " << end_one.x << " " << end_one.y << " " << end_one.z << " " << end_two.x << " " << end_two.y << " " << end_two.z
                           << " " << arc_mm << " " << chord_length * 1000.f << " " << sag_mm << "\n";
                }
            }
        }
        std::cout << "DIAG stalkdump file=" << cfg.s("diag.stalkdump") << std::endl;
    }

    // diag.flowerdump <path>: every peduncle, flower and pod with its phytomer (dumpFlowers)
    dumpFlowers(cfg, context, plantarchitecture, plantIDs, sites);

    // diag.petiolecensus 1: every petiole in the scene with the leaflets that should be on it, to account for the
    // bare stalks in the renders. A petiole counts as bare when none of the leaf objects the phytomer lists for it
    // still exist, and as stunted when they exist but carry almost no area. Reported against the phytomer's age and
    // its node's position from the shoot tip, since a petiole at the apex is expected to lead its leaflets.
    if (cfg.i("diag.petiolecensus", 0)) {
        size_t petioles = 0, bare = 0, stunted = 0, missing_some = 0;
        std::vector<float> bare_ages, leafy_ages, areas;
        for (size_t k = 0; k < plantIDs.size(); k++) {
            for (uint shootID: plantarchitecture.getAllShootIDs(plantIDs[k])) {
                if (plantarchitecture.isShootPruned(plantIDs[k], shootID)) continue;
                const auto shoot = plantarchitecture.getPlantShoot(plantIDs[k], shootID);
                const size_t node_count = shoot->phytomers.size();
                for (size_t n = 0; n < node_count; n++) {
                    const auto &phytomer = shoot->phytomers[n];
                    for (size_t petiole_index = 0; petiole_index < phytomer->leaf_objIDs.size(); petiole_index++) {
                        const std::vector<uint> &leaflets = phytomer->leaf_objIDs[petiole_index];
                        const float petiole_length_mm = petiole_index < phytomer->petiole_length.size() ? phytomer->petiole_length[petiole_index] * 1000.f : -1.f;
                        const float leaf_scale = petiole_index < phytomer->current_leaf_scale_factor.size() ? phytomer->current_leaf_scale_factor[petiole_index] : -1.f;
                        // Closest approach between this petiole's own geometry and the leaflets it carries. A leaflet
                        // sitting on the end of its stalk touches it, so anything but a few millimetres here means the
                        // blade was left behind when the petiole moved or grew -- a stalk rendered ending in nothing.
                        float gap_mm = -1.f;
                        if (petiole_index < phytomer->petiole_objIDs.size() && context.doesObjectExist(phytomer->petiole_objIDs[petiole_index])) {
                            std::vector<vec3> stalk;
                            for (uint UUID: context.getObjectPrimitiveUUIDs(phytomer->petiole_objIDs[petiole_index])) {
                                const std::vector<vec3> v = context.getPrimitiveVertices(UUID);
                                stalk.insert(stalk.end(), v.begin(), v.end());
                            }
                            float nearest = 1e9f;
                            for (uint objID: leaflets) {
                                if (!context.doesObjectExist(objID)) continue;
                                for (uint UUID: context.getObjectPrimitiveUUIDs(objID)) {
                                    for (const vec3 &leaf_vertex: context.getPrimitiveVertices(UUID)) {
                                        for (const vec3 &stalk_vertex: stalk) nearest = std::min(nearest, (leaf_vertex - stalk_vertex).magnitude());
                                    }
                                }
                            }
                            if (nearest < 1e8f) gap_mm = nearest * 1000.f;
                        }
                        petioles++;
                        size_t existing = 0;
                        float area = 0.f;
                        for (uint objID: leaflets) {
                            if (!context.doesObjectExist(objID)) continue;
                            existing++;
                            for (uint UUID: context.getObjectPrimitiveUUIDs(objID)) area += context.getPrimitiveArea(UUID);
                        }
                        const float area_mm2 = area * 1e6f;
                        if (leaflets.empty() || existing == 0) {
                            bare++;
                            bare_ages.push_back(phytomer->age);
                        } else {
                            if (existing < leaflets.size()) missing_some++;
                            if (area_mm2 < 1.f) stunted++;
                            leafy_ages.push_back(phytomer->age);
                            areas.push_back(area_mm2);
                        }
                        std::cout << "PETIOLE plant=" << k << " shoot=" << shootID << " node=" << n << " of " << node_count
                                  << " from_tip=" << (node_count - 1 - n) << " age=" << phytomer->age << " leaflets=" << leaflets.size()
                                  << " existing=" << existing << " area_mm2=" << area_mm2 << " petiole_mm=" << petiole_length_mm
                                  << " leaf_scale=" << leaf_scale << " gap_mm=" << gap_mm << " petiole_obj="
                                  << (petiole_index < phytomer->petiole_objIDs.size() ? int(phytomer->petiole_objIDs[petiole_index]) : -1) << " leaf_objs=";
                        for (size_t j = 0; j < leaflets.size(); j++) std::cout << (j ? "," : "") << leaflets[j];
                        std::cout << std::endl;
                    }
                }
            }
        }
        auto median = [](std::vector<float> v) {
            if (v.empty()) return -1.f;
            std::sort(v.begin(), v.end());
            return v[v.size() / 2];
        };
        // The walk above visits live shoots only. If the Context holds more petiole or leaf objects than it visited,
        // the extra geometry belongs to no live phytomer -- a pruned shoot whose stalks were left behind would show
        // in a render as a petiole that can never have leaves.
        size_t petiole_objects = 0, leaf_objects = 0, pruned_shoots = 0, peduncle_objects = 0, flower_objects = 0, fruit_objects = 0;
        float peduncle_length_mm = 0.f;
        for (uint plantID: plantIDs) {
            petiole_objects += plantarchitecture.getPlantPetioleObjectIDs(plantID).size();
            leaf_objects += plantarchitecture.getPlantLeafObjectIDs(plantID).size();
            flower_objects += plantarchitecture.getPlantFlowerObjectIDs(plantID).size();
            fruit_objects += plantarchitecture.getPlantFruitObjectIDs(plantID).size();
            for (uint objID: plantarchitecture.getPlantPeduncleObjectIDs(plantID)) {
                peduncle_objects++;
                vec3 lo(1e9f, 1e9f, 1e9f), hi(-1e9f, -1e9f, -1e9f);
                for (uint UUID: context.getObjectPrimitiveUUIDs(objID)) {
                    for (const vec3 &v: context.getPrimitiveVertices(UUID)) {
                        lo = make_vec3(std::min(lo.x, v.x), std::min(lo.y, v.y), std::min(lo.z, v.z));
                        hi = make_vec3(std::max(hi.x, v.x), std::max(hi.y, v.y), std::max(hi.z, v.z));
                    }
                }
                if (hi.x > lo.x) peduncle_length_mm += (hi - lo).magnitude() * 1000.f;
            }
            for (uint shootID: plantarchitecture.getAllShootIDs(plantID)) {
                if (plantarchitecture.isShootPruned(plantID, shootID)) pruned_shoots++;
            }
        }
        std::cout << "DIAG petioleorphans petiole_objects=" << petiole_objects << " petioles_walked=" << petioles
                  << " leaf_objects=" << leaf_objects << " pruned_shoots=" << pruned_shoots
                  << " peduncles=" << peduncle_objects << " peduncle_mean_mm=" << (peduncle_objects ? peduncle_length_mm / float(peduncle_objects) : 0.f)
                  << " flowers=" << flower_objects << " fruits=" << fruit_objects << std::endl;
        std::cout << "DIAG petiolecensus petioles=" << petioles << " bare=" << bare << " missing_some=" << missing_some
                  << " stunted=" << stunted << " bare_fraction=" << (petioles ? double(bare) / double(petioles) : 0.0)
                  << " median_age_bare=" << median(bare_ages) << " median_age_leafy=" << median(leafy_ages)
                  << " median_area_mm2=" << median(areas) << std::endl;
    }


    tagSites(context, plantarchitecture, sites);
    dumpLeaves(cfg, context, plantarchitecture, plantIDs);
    if (sites_out != nullptr) {
        *sites_out = sites;
    }
    std::cout << context.getPrimitiveCount() * 1e-6 << "M primitives" << std::endl;
    {
        // Canopy top height drives the camera-to-canopy distance and therefore
        // the GSD. The real rig sits 1.64 m above ground over a 0.54 m canopy
        // (1.10 m working distance, 0.440 mm/px); matching that is what closes
        // the measured 1.27x object-size gap.
        float zmax = 0.f;
        for (uint id: plantIDs)
            for (uint u: plantarchitecture.getAllPlantUUIDs(id))
                for (const vec3 &v: context.getPrimitiveVertices(u)) zmax = std::max(zmax, v.z);
        std::cout << "DIAG canopy_top_m=" << zmax
                  << " working_distance_m=" << (cfg.f("camera.height") - zmax) << std::endl;
    }

    return plantIDs;
}

// canopy.plant_xml <list>: the canopy read from plant-structure XML files instead of grown, so that plants made
// elsewhere (a refined reconstruction, or a grown plant written out by diag.write_plant_xml) go through exactly
// the raster and render paths a grown canopy does. One line per file,
//     path [yaw_deg [seed]]
// each file's plants standing where its <base_position> says. yaw_deg turns them about that base as buildCanopy
// turns a site (0 when the file already carries its orientation); seed names the stream the leaf chlorophyll
// draw uses, so a plant written out and read back keeps its leaf colours. Nothing is grown and no leaf angle is
// re-imposed: the file is the geometry.
std::vector<uint> loadCanopyXML(const Config &cfg, Context &context, PlantArchitecture &plantarchitecture,
                                std::vector<Site> *sites_out = nullptr) {
    plantarchitecture.optionalOutputObjectData("plantID");
    plantarchitecture.optionalOutputObjectData("openflowerID");
    plantarchitecture.optionalOutputObjectData("closedflowerID");
    plantarchitecture.optionalOutputObjectData("fruitID");
    configurePlantModel(cfg, plantarchitecture);

    const std::string list_file = cfg.s("canopy.plant_xml");
    std::ifstream f(list_file);
    if (!f) {
        helios_runtime_error("ERROR (loadCanopyXML): cannot open canopy.plant_xml " + list_file);
    }
    std::vector<Site> sites;
    std::string line;
    while (std::getline(f, line)) {
        const size_t c = line.find('#');
        if (c != std::string::npos) line = line.substr(0, c);
        std::istringstream ss(line);
        std::string path;
        if (!(ss >> path)) continue;
        float yaw_deg = 0.f;
        unsigned seed = unsigned(sites.size() + 1);
        ss >> yaw_deg >> seed;
        for (uint pid: plantarchitecture.readPlantStructureXML(path, true)) {
            Site s;
            s.plantID = pid;
            s.position = plantarchitecture.getPlantBasePosition(pid);
            s.yaw_rad = deg2rad(yaw_deg);
            s.age_days = plantarchitecture.getPlantAge(pid);
            s.seed = seed;
            if (s.yaw_rad != 0.f) {
                // Objects, not primitives: a primitive-level transform is discarded for the tube organs (see buildCanopy).
                const std::vector<uint> objects = plantarchitecture.getAllPlantObjectIDs(pid);
                context.rotateObject(objects, s.yaw_rad, s.position, make_vec3(0, 0, 1));
                std::set<uint> covered;
                for (uint objID: objects) {
                    for (uint u: context.getObjectPrimitiveUUIDs(objID)) covered.insert(u);
                }
                std::vector<uint> loose;
                for (uint u: plantarchitecture.getAllPlantUUIDs(pid)) {
                    if (!covered.count(u)) loose.push_back(u);
                }
                if (!loose.empty()) context.rotatePrimitive(loose, s.yaw_rad, s.position, make_vec3(0, 0, 1));
            }
            sites.push_back(s);
        }
    }
    std::vector<uint> plantIDs;
    for (const Site &s: sites) plantIDs.push_back(s.plantID);
    std::cout << "DIAG plant_xml=" << list_file << " plants=" << plantIDs.size() << std::endl;

    assignLeafChlorophyll(cfg, context, plantarchitecture, plantIDs, sites);
    tagSites(context, plantarchitecture, sites);
    dumpLeaves(cfg, context, plantarchitecture, plantIDs);
    dumpLeafTransforms(cfg, context, plantarchitecture, plantIDs);
    dumpLeafVertices(cfg, context, plantarchitecture, plantIDs);
    dumpLeafUVFit(cfg, context, plantarchitecture, plantIDs);
    dumpFlowers(cfg, context, plantarchitecture, plantIDs, sites);
    if (sites_out != nullptr) {
        *sites_out = sites;
    }
    std::cout << context.getPrimitiveCount() * 1e-6 << "M primitives" << std::endl;
    return plantIDs;
}

// canopy.obj_list <list> (I/O addition, 2026-09-28): plain meshes (baseline reconstructions, dumped facets) instead of
// plants. One line per OBJ:  path [tx ty tz [rx_deg ry_deg rz_deg [scale]]]  -- all optional, identity by default.
// The mesh is loaded as is (Context::loadOBJ, vertices in scene metres, z up, no rescale), then scaled about its own
// centroid, rotated about that centroid by rx, ry, rz (in that order, about the world x, y, z axes), then translated
// by (tx, ty, tz). Every primitive of line k gets siteIndex k + 1 (the site map) and a neutral green reflectance
// (spectrum_green); there are no plants, so no leaf optics apply. Returns no plant IDs.
std::vector<uint> loadCanopyOBJ(const Config &cfg, Context &context) {
    const std::string list_file = cfg.s("canopy.obj_list");
    std::ifstream f(list_file);
    if (!f) helios_runtime_error("ERROR (loadCanopyOBJ): cannot open canopy.obj_list " + list_file);
    std::string line;
    int k = 0;
    size_t n_prims = 0;
    while (std::getline(f, line)) {
        const size_t c = line.find('#');
        if (c != std::string::npos) line = line.substr(0, c);
        std::istringstream ss(line);
        std::string path;
        if (!(ss >> path)) continue;
        float tx = 0, ty = 0, tz = 0, rx = 0, ry = 0, rz = 0, sc = 1;
        ss >> tx >> ty >> tz >> rx >> ry >> rz >> sc;
        // Loaded 1000x larger and scaled back: loadOBJ drops every triangle under 1e-8 m^2 (Context_fileIO.cpp,
        // MIN_TRIANGLE_AREA_THRESHOLD), which removed whole meshes of seedling leaves (facets ~5e-10 m^2).
        const float kUp = 1000.f;
        std::vector<uint> U = context.loadOBJ(path.c_str(), make_vec3(0, 0, 0), make_vec3(kUp, kUp, kUp), nullrotation,
                                              RGB::green, "ZUP", true);
        if (!U.empty()) context.scalePrimitiveAboutPoint(U, make_vec3(1.f / kUp, 1.f / kUp, 1.f / kUp), make_vec3(0, 0, 0));
        if (U.empty()) helios_runtime_error("ERROR (loadCanopyOBJ): no primitives in " + path);
        vec3 cen(0, 0, 0);
        size_t nv = 0;
        for (uint u: U)
            for (const vec3 &v: context.getPrimitiveVertices(u)) { cen = cen + v; nv++; }
        cen = cen / float(std::max<size_t>(nv, 1));
        if (sc != 1.f) context.scalePrimitiveAboutPoint(U, make_vec3(sc, sc, sc), cen);
        if (rx != 0.f) context.rotatePrimitive(U, deg2rad(rx), cen, make_vec3(1, 0, 0));
        if (ry != 0.f) context.rotatePrimitive(U, deg2rad(ry), cen, make_vec3(0, 1, 0));
        if (rz != 0.f) context.rotatePrimitive(U, deg2rad(rz), cen, make_vec3(0, 0, 1));
        if (tx != 0.f || ty != 0.f || tz != 0.f) context.translatePrimitive(U, make_vec3(tx, ty, tz));
        context.setPrimitiveData(U, "siteIndex", k + 1);
        context.setPrimitiveData(U, "reflectivity_spectrum", "spectrum_green");
        std::cout << "SITE " << k << " obj=" << path << " primitives=" << U.size() << std::endl;
        n_prims += U.size();
        k++;
    }
    std::cout << "DIAG obj_list=" << list_file << " objects=" << k << " primitives=" << n_prims << std::endl;
    return {};
}

//! The canopy a pass draws: read from canopy.plant_xml when it is set, grown by buildCanopy() otherwise.
std::vector<uint> makeCanopy(const Config &cfg, Context &context, PlantArchitecture &plantarchitecture, unsigned scene_seed,
                             std::vector<Site> *sites_out = nullptr) {
    if (cfg.has("canopy.obj_list")) {
        return loadCanopyOBJ(cfg, context);
    }
    if (cfg.has("canopy.plant_xml")) {
        return loadCanopyXML(cfg, context, plantarchitecture, sites_out);
    }
    return buildCanopy(cfg, context, plantarchitecture, scene_seed, sites_out);
}

// ---------------------------------------------------------------- geometry ---

// Rasterized geometry pass: same canopy, same camera geometry, no radiative transfer.
//
// Every parameter this project tunes falls into one of two groups. Appearance parameters (leaf
// pigments, soil reflectance, light flux, specular response, the colour pipeline) need the ray
// tracer. Geometry parameters (flower and leaf prototype scale, inflorescence pitch, plant
// spacing, row count, germination fraction, phenology) determine only where matter is in space
// and therefore how large and how numerous objects are in the frame -- and those are answered
// exactly as well by a rasterizer, which does not integrate a single ray.
//
// The camera is matched to the RadiationModel camera rather than approximated. Both are pinhole
// perspective projections; the RadiationModel takes a horizontal field of view and the Visualizer
// a vertical one, so HFOV is converted here through the pixel aspect ratio.
//
// Deliberately absent: the T4 rover (1.1M primitives, occludes nothing the annotations depend on
// at nadir), the soil and leaf spectra, and the lights. The ground tile is kept because objects
// clipped against it would otherwise be annotated through the floor.
int geom(const Config &cfg, unsigned seed) {

    Context context;
    context.seedRandomGenerator(seed);
    PlantArchitecture plantarchitecture(&context);

    const auto t0 = std::chrono::steady_clock::now();
    const std::vector<uint> plantIDs = buildCanopy(cfg, context, plantarchitecture, seed);
    const auto t1 = std::chrono::steady_clock::now();

    std::vector<uint> ground = context.addTile(make_vec3(0, 0, -0.01), {3, 3.048}, nullrotation,
                                               make_int2(20, 20), make_RGBcolor(0.45, 0.36, 0.28));
    context.setPrimitiveData(ground, "twosided_flag", uint(0));

    const int2 res = make_int2(cfg.i("camera.resolution_x"), cfg.i("camera.resolution_y"));
    // RadiationModel::updateCameraParameters derives the vertical extent of the view plane from
    // the horizontal one through the resolution aspect ratio (FOV_aspect_ratio is auto-computed to
    // keep pixels square), giving VFOV = 2*atan( tan(HFOV/2) * res_y / res_x ). glm::perspective,
    // which the Visualizer uses, takes that vertical angle directly.
    const float hfov = cfg.f("camera.hfov") * float(M_PI) / 180.f;
    const float vfov = 2.f * std::atan(std::tan(0.5f * hfov) * float(res.y) / float(res.x)) * 180.f / float(M_PI);

    SyntheticAnnotation annotation(&context);
    annotation.disableMessages();
    annotation.setWindowSize(uint(res.x), uint(res.y));
    annotation.setCameraFieldOfView(vfov);
    annotation.setCameraPosition(make_vec3(0, 0, cfg.f("camera.height")), make_vec3(0, 0, 0));
    annotation.setMinimumLabelPixels(cfg.i("geom.min_label_pixels", 10));
    if (!cfg.i("geom.write_rgb", 0)) {
        annotation.disableRGBRendering();
    }

    // One annotation group per flower object, matching what the ray-traced path writes from
    // openflowerID/closedflowerID. The two streams are labelled separately here -- the size
    // distributions of buds and open flowers are different populations and conflating them is
    // what let a bimodal synthetic distribution pass a median-based comparison.
    std::vector<std::vector<uint>> open_groups, closed_groups, leaf_groups;
    for (uint id: plantIDs) {
        for (uint objID: plantarchitecture.getPlantFlowerObjectIDs(id)) {
            const std::vector<uint> uuid = context.getObjectPrimitiveUUIDs(objID);
            if (context.doesObjectDataExist(objID, "openflowerID")) {
                open_groups.push_back(uuid);
            } else if (context.doesObjectDataExist(objID, "closedflowerID")) {
                closed_groups.push_back(uuid);
            }
        }
        if (cfg.i("geom.label_leaves", 1)) {
            for (uint objID: plantarchitecture.getPlantLeafObjectIDs(id)) {
                leaf_groups.push_back(context.getObjectPrimitiveUUIDs(objID));
            }
        }
    }
    annotation.labelPrimitives(open_groups, "flower_open");
    annotation.labelPrimitives(closed_groups, "flower_closed");
    if (!leaf_groups.empty()) {
        annotation.labelPrimitives(leaf_groups, "leaf");
    }

    annotation.enableObjectDetection();
    annotation.disableSemanticSegmentation();
    if (cfg.i("geom.instance_masks", 0)) {
        annotation.enableInstanceSegmentation();
    } else {
        annotation.disableInstanceSegmentation();
    }

    std::stringstream odir;
    odir << cfg.s("output.folder") << "geom_" << std::setfill('0') << std::setw(3) << cfg.i("canopy.age")
         << "_" << std::setfill('0') << std::setw(7) << seed << "/";
    // SyntheticAnnotation::render() creates its per-view sub-directory but not the parent chain.
    std::filesystem::create_directories(odir.str());
    const auto t2 = std::chrono::steady_clock::now();
    annotation.render(odir.str().c_str());
    const auto t3 = std::chrono::steady_clock::now();

    // Vegetation cover, read back from the label image. With every leaf labelled, a non-background
    // pixel IS vegetation, so the rasterized pass measures canopy density without shading anything.
    // This is not incidental: the sweeps that chose the leaf scale ran with leaf labelling off for
    // speed, which is exactly why they could not see that the widened scale overshot cover by three
    // points. It is on by default now, and reported by default.
    double veg_cover = -1.0;
    if (cfg.i("geom.label_leaves", 1)) {
        const std::string idfile = odir.str() + "view00000/pixelID_combined.txt";
        std::ifstream idmap(idfile);
        if (!idmap) {
            helios_runtime_error("ERROR (geom): expected the label image at " + idfile +
                                 " in order to measure canopy cover, but it could not be opened. "
                                 "Either object detection was disabled, or render() failed to write it.");
        }
        constexpr long background_id = 16777215; // white, as written by SyntheticAnnotation
        long value = 0, total = 0, vegetation = 0;
        while (idmap >> value) {
            total++;
            if (value != background_id) vegetation++;
        }
        if (total == 0) {
            helios_runtime_error("ERROR (geom): the label image at " + idfile + " contained no pixels.");
        }
        veg_cover = double(vegetation) / double(total);
    }

    const auto ms = [](auto a, auto b) { return std::chrono::duration_cast<std::chrono::milliseconds>(b - a).count(); };
    std::cout << "DIAG geom_build_ms=" << ms(t0, t1) << " geom_raster_ms=" << ms(t2, t3)
              << " primitives=" << context.getPrimitiveCount()
              << " flowers_open=" << open_groups.size() << " flowers_closed=" << closed_groups.size()
              << " leaves=" << leaf_groups.size();
    if (veg_cover >= 0.0) std::cout << " veg_cover=" << veg_cover;
    std::cout << std::endl;
    std::cout << "wrote " << odir.str() << std::endl;
    return 0;
}

// -------------------------------------------------------------- rasterizer ---

// Software label rasterizer: the scene as the camera sees it, without the ray tracer.
//
// Fitting one real image needs many geometric evaluations -- which pixels are canopy, which leaf
// is on top, which way it faces -- and none of them needs light transport. The ray tracer costs
// GPU-minutes per frame; the OpenGL annotation pass needs a display or an EGL device and writes
// text files. This is a plain z-buffer over the same pinhole camera the RadiationModel uses
// (nadir at camera.height, camera.hfov across camera.resolution_x, square pixels), with the leaf
// cut-out textures honoured through their transparency masks, so its maps register to the
// ray-traced image pixel for pixel. It runs on any CPU and costs about a second per million
// primitives.
//
// Output, all row-major H x W, little-endian, raw, named <base>_<map>.<dtype>:
//   site.u16     1-based site index of the plant owning the pixel, 0 for ground or nothing
//   obj.u32      1-based organ index (leaf, flower or fruit object), 0 otherwise
//   class.u8     0 ground, 1 leaf, 2 open flower, 3 closed flower, 4 stem/petiole/peduncle (with
//                raster.split_stems 1: 4 petiole, 7 internode, 8 peduncle),
//                5 fruit, 6 rover, 255 nothing
//   depth.f32    distance from the camera plane, metres
//   normal.f32   3 floats per pixel, unit surface normal turned to face the camera
// plus <base>_raster.json describing the shapes and the crop offset.

struct RasterCamera {
    int W = 0, H = 0;
    float cam_z = 0.f; //!< camera height above the bed
    float f_px = 0.f; //!< focal length in pixels
    float sx = 1.f, sy = 1.f; //!< image column grows with sx * world x; image row grows with -sy * world y
};

struct RasterTag {
    uint16_t site = 0;
    uint32_t obj = 0;
    uint8_t cls = 255;
};

struct RasterMaps {
    int W = 0, H = 0;
    std::vector<float> depth;
    std::vector<uint16_t> site;
    std::vector<uint32_t> obj;
    std::vector<uint8_t> cls;
    std::vector<float> normal;
    void init(int w, int h) {
        W = w;
        H = h;
        depth.assign(size_t(w) * h, std::numeric_limits<float>::infinity());
        site.assign(size_t(w) * h, 0);
        obj.assign(size_t(w) * h, 0);
        cls.assign(size_t(w) * h, 255);
        normal.assign(size_t(w) * h * 3, 0.f);
    }
};

// Perspective-correct scan conversion of one triangle into the maps. `uv` is per vertex and is
// only read when `mask` is set, in which case a pixel whose texture sample is transparent is
// skipped -- the same rule the ray tracer applies, so leaf outlines match its images.
void rasterTriangle(RasterMaps &m, const RasterCamera &cam, const vec3 v[3], const vec2 uv[3],
                    const std::vector<std::vector<bool>> *mask, const RasterTag &tag, const vec3 &normal) {
    float px[3], py[3], invd[3];
    for (int k = 0; k < 3; k++) {
        const float d = cam.cam_z - v[k].z;
        if (d < 1e-3f) return; // at or behind the lens
        invd[k] = 1.f / d;
        px[k] = 0.5f * float(cam.W) + cam.sx * cam.f_px * v[k].x * invd[k];
        py[k] = 0.5f * float(cam.H) - cam.sy * cam.f_px * v[k].y * invd[k];
    }
    const float area = (px[1] - px[0]) * (py[2] - py[0]) - (px[2] - px[0]) * (py[1] - py[0]);
    if (std::fabs(area) < 1e-12f) return;
    const float inv_area = 1.f / area;
    const int x0 = std::max(0, int(std::floor(std::min({px[0], px[1], px[2]}))));
    const int x1 = std::min(cam.W - 1, int(std::ceil(std::max({px[0], px[1], px[2]}))));
    const int y0 = std::max(0, int(std::floor(std::min({py[0], py[1], py[2]}))));
    const int y1 = std::min(cam.H - 1, int(std::ceil(std::max({py[0], py[1], py[2]}))));
    if (x0 > x1 || y0 > y1) return;
    const int mask_h = mask ? int(mask->size()) : 0;
    const int mask_w = (mask && mask_h > 0) ? int((*mask)[0].size()) : 0;
    for (int j = y0; j <= y1; j++) {
        const float cy = float(j) + 0.5f;
        for (int i = x0; i <= x1; i++) {
            const float cx = float(i) + 0.5f;
            const float w0 = ((px[1] - cx) * (py[2] - cy) - (px[2] - cx) * (py[1] - cy)) * inv_area;
            const float w1 = ((px[2] - cx) * (py[0] - cy) - (px[0] - cx) * (py[2] - cy)) * inv_area;
            const float w2 = 1.f - w0 - w1;
            if (w0 < 0.f || w1 < 0.f || w2 < 0.f) continue;
            const float id = w0 * invd[0] + w1 * invd[1] + w2 * invd[2];
            const float d = 1.f / id;
            const size_t p = size_t(j) * cam.W + i;
            if (d >= m.depth[p]) continue;
            if (mask_w > 0 && mask_h > 0) {
                const float u = (w0 * uv[0].x * invd[0] + w1 * uv[1].x * invd[1] + w2 * uv[2].x * invd[2]) / id;
                const float vv = (w0 * uv[0].y * invd[0] + w1 * uv[1].y * invd[1] + w2 * uv[2].y * invd[2]) / id;
                int c = int(std::floor(float(mask_w - 1) * u));
                int r = int(std::floor(float(mask_h - 1) * (1.f - vv)));
                c = std::min(std::max(c, 0), mask_w - 1);
                r = std::min(std::max(r, 0), mask_h - 1);
                if (!(*mask)[r][c]) continue;
            }
            m.depth[p] = d;
            m.site[p] = tag.site;
            m.obj[p] = tag.obj;
            m.cls[p] = tag.cls;
            m.normal[3 * p] = normal.x;
            m.normal[3 * p + 1] = normal.y;
            m.normal[3 * p + 2] = normal.z;
        }
    }
}

void rasterPrimitive(RasterMaps &m, const RasterCamera &cam, const Context &context, uint UUID, const RasterTag &tag) {
    const PrimitiveType type = context.getPrimitiveType(UUID);
    if (type != PRIMITIVE_TYPE_PATCH && type != PRIMITIVE_TYPE_TRIANGLE) return;
    const std::vector<vec3> verts = context.getPrimitiveVertices(UUID);
    vec3 n = context.getPrimitiveNormal(UUID);
    if (n.z < 0.f) n = -n; // the side the nadir camera sees
    const std::vector<std::vector<bool>> *mask = nullptr;
    std::vector<vec2> uv;
    if (context.primitiveTextureHasTransparencyChannel(UUID)) {
        mask = context.getPrimitiveTextureTransparencyData(UUID);
        uv = context.getPrimitiveTextureUV(UUID);
        if (uv.size() != verts.size()) {
            // Default texture coordinates of an untextured-UV patch/triangle, in vertex order.
            uv = {make_vec2(0, 0), make_vec2(1, 0), make_vec2(1, 1), make_vec2(0, 1)};
            uv.resize(verts.size());
        }
    } else {
        uv.assign(verts.size(), make_vec2(0, 0));
    }
    if (verts.size() == 3) {
        const vec3 v[3] = {verts[0], verts[1], verts[2]};
        const vec2 t[3] = {uv[0], uv[1], uv[2]};
        rasterTriangle(m, cam, v, t, mask, tag, n);
    } else if (verts.size() == 4) {
        const vec3 va[3] = {verts[0], verts[1], verts[2]};
        const vec2 ta[3] = {uv[0], uv[1], uv[2]};
        rasterTriangle(m, cam, va, ta, mask, tag, n);
        const vec3 vb[3] = {verts[0], verts[2], verts[3]};
        const vec2 tb[3] = {uv[0], uv[2], uv[3]};
        rasterTriangle(m, cam, vb, tb, mask, tag, n);
    }
}

template<typename T>
void writeRaw(const std::string &path, const std::vector<T> &data, size_t offset, size_t count) {
    std::ofstream f(path, std::ios::binary);
    if (!f) helios_runtime_error("ERROR (raster): cannot write " + path);
    f.write(reinterpret_cast<const char *>(data.data() + offset), std::streamsize(count * sizeof(T)));
}

// I/O addition (2026-09-29): where the Syn2Real_cowpea assets are (soil spectra, T4 rover body and its reflectance).
// Upstream hard-codes "../../Syn2Real_cowpea", relative to the working directory (<project>/build), which is the
// default here too. paths.syn2real_dir moves the whole folder; paths.soil_spec_xml names the soil spectra alone.
static std::string syn2realPath(const Config &cfg, const std::string &rel) {
    return cfg.s("paths.syn2real_dir", "../../Syn2Real_cowpea") + "/" + rel;
}

int raster(const Config &cfg, unsigned seed) {

    Context context;
    context.seedRandomGenerator(seed);
    PlantArchitecture plantarchitecture(&context);
    const auto t0 = std::chrono::steady_clock::now();
    std::vector<Site> sites;
    const std::vector<uint> plantIDs = makeCanopy(cfg, context, plantarchitecture, seed, &sites);
    const auto t1 = std::chrono::steady_clock::now();

    RasterCamera cam;
    const float scale = cfg.f("raster.scale", 1.f);
    cam.W = std::max(1, int(std::lround(cfg.i("camera.resolution_x") * scale)));
    cam.H = std::max(1, int(std::lround(cfg.i("camera.resolution_y") * scale)));
    cam.cam_z = cfg.f("camera.height");
    cam.f_px = 0.5f * float(cam.W) / std::tan(0.5f * deg2rad(cfg.f("camera.hfov")));
    // Axis orientation of the image relative to the bed. The ray tracer's JPEG is written with
    // both axes flipped relative to its internal buffer; these signs put the rasterized maps
    // into the JPEG's frame and are verified against a ray-traced siteIndex label map.
    cam.sx = cfg.f("raster.sx", 1.f);
    cam.sy = cfg.f("raster.sy", 1.f);

    RasterMaps maps;
    maps.init(cam.W, cam.H);

    // Ground first: a large flat tile, cheap, so that "nothing" only remains beyond the bed.
    if (cfg.i("raster.ground", 1)) {
        const std::vector<uint> ground = context.addTile(make_vec3(0, 0, -0.01), {3, 3.048}, nullrotation, make_int2(20, 20));
        RasterTag tag;
        tag.cls = 0;
        for (uint u: ground) rasterPrimitive(maps, cam, context, u, tag);
    }
    // The rover body, when the real frame carries it: 1.1M primitives, so opt in.
    if (cfg.i("raster.load_rover", 0)) {
        const std::vector<uint> rover = context.loadOBJ(syn2realPath(cfg, "obj/T4rover_highres.obj").c_str(), make_vec3(0, 0, -0.05), 0, nullrotation, RGB::black);
        RasterTag tag;
        tag.cls = 6;
        for (uint u: rover) rasterPrimitive(maps, cam, context, u, tag);
    }

    // Which sites to draw. Empty = all; otherwise a comma-separated list of 0-based site indices,
    // which is how the fitting code isolates one plant's silhouette at its true place in the frame.
    std::vector<bool> draw(sites.size(), true);
    {
        const std::string only = cfg.s("raster.only_sites", "");
        if (!only.empty()) {
            draw.assign(sites.size(), false);
            std::stringstream ss(only);
            std::string tok;
            while (std::getline(ss, tok, ',')) {
                const int k = std::stoi(tok);
                if (k < 0) continue; // "-1": draw no site at all (the scene without any plant)
                if (k >= int(sites.size())) {
                    helios_runtime_error("ERROR (raster): raster.only_sites index " + tok + " is outside 0.." + std::to_string(sites.size()) + ".");
                }
                draw[k] = true;
            }
        }
    }

    uint32_t obj_index = 0;
    size_t n_leaves = 0, n_flowers = 0;
    // Helios object ID -> the organ index written into obj.u32, so that a per-organ measurement made on the
    // geometry (diag.leafruler) can be joined to the organ's visible pixels. The map's own indices are a
    // running count in rasterization order and mean nothing outside the run that produced them.
    std::map<uint, uint32_t> organ_index_of;
    // Draw one site's organs into a map set. Shared by the whole-scene pass and the per-site
    // batch below.
    auto draw_site = [&](RasterMaps &m, size_t k) {
        const uint pid = sites[k].plantID;
        RasterTag tag;
        tag.site = uint16_t(k + 1);
        auto raster_objects = [&](const std::vector<uint> &objIDs, RasterTag t, bool number) {
            for (uint objID: objIDs) {
                if (number) {
                    t.obj = ++obj_index;
                    organ_index_of[objID] = t.obj;
                }
                for (uint u: context.getObjectPrimitiveUUIDs(objID)) rasterPrimitive(m, cam, context, u, t);
            }
        };
        tag.cls = 1;
        const std::vector<uint> leaves = plantarchitecture.getPlantLeafObjectIDs(pid);
        n_leaves += leaves.size();
        raster_objects(leaves, tag, true);
        for (uint objID: plantarchitecture.getPlantFlowerObjectIDs(pid)) {
            tag.cls = context.doesObjectDataExist(objID, "openflowerID") ? 2 : 3;
            raster_objects({objID}, tag, true);
            n_flowers++;
        }
        tag.cls = 5;
        raster_objects(plantarchitecture.getPlantFruitObjectIDs(pid), tag, true);
        // raster.split_stems 1 separates the three stem organs, which share class 4 everywhere else, so that a bare
        // stalk in a render can be attributed to one of them. Off by default: class 4 means "stem" to every consumer.
        const bool split_stems = cfg.i("raster.split_stems", 0) != 0;
        tag.cls = 4;
        tag.obj = 0;
        // Petioles are numbered too when the stem organs are split out, so that a stalk's pixels can be traced back
        // to the phytomer that carries it and to the leaflets that should be on its end.
        raster_objects(plantarchitecture.getPlantPetioleObjectIDs(pid), tag, split_stems);
        tag.cls = split_stems ? 7 : 4;
        raster_objects(plantarchitecture.getPlantInternodeObjectIDs(pid), tag, false);
        tag.cls = split_stems ? 8 : 4;
        raster_objects(plantarchitecture.getPlantPeduncleObjectIDs(pid), tag, false);
    };

    const std::string out = cfg.s("output.folder");
    std::filesystem::create_directories(out);
    // Write a map set, optionally cropped to its plant pixels (the offset goes in the sidecar).
    auto write_maps = [&](const RasterMaps &m, const std::string &base, bool crop) {
        int cx0 = 0, cy0 = 0, cx1 = cam.W - 1, cy1 = cam.H - 1;
        if (crop) {
            cx0 = cam.W; cy0 = cam.H; cx1 = -1; cy1 = -1;
            for (int j = 0; j < cam.H; j++)
                for (int i = 0; i < cam.W; i++)
                    if (m.site[size_t(j) * cam.W + i] != 0) {
                        cx0 = std::min(cx0, i); cx1 = std::max(cx1, i);
                        cy0 = std::min(cy0, j); cy1 = std::max(cy1, j);
                    }
            if (cx1 < cx0) { cx0 = cy0 = 0; cx1 = cy1 = -1; }
        }
        const int cw = cx1 - cx0 + 1, ch = cy1 - cy0 + 1;
        auto crop_write = [&](const std::string &name, const auto &data, int channels) {
            using T = typename std::remove_reference<decltype(data)>::type::value_type;
            std::vector<T> window;
            window.reserve(size_t(std::max(cw, 0)) * std::max(ch, 0) * channels);
            for (int j = cy0; j <= cy1; j++)
                for (int i = cx0; i <= cx1; i++)
                    for (int c = 0; c < channels; c++) window.push_back(data[(size_t(j) * cam.W + i) * channels + c]);
            writeRaw(out + base + "_" + name, window, 0, window.size());
        };
        crop_write("site.u16", m.site, 1);
        crop_write("obj.u32", m.obj, 1);
        crop_write("class.u8", m.cls, 1);
        crop_write("depth.f32", m.depth, 1);
        crop_write("normal.f32", m.normal, 3);
        std::ofstream js(out + base + "_raster.json");
        js << "{\"W\": " << cam.W << ", \"H\": " << cam.H << ", \"crop_x0\": " << cx0 << ", \"crop_y0\": " << cy0
           << ", \"crop_w\": " << cw << ", \"crop_h\": " << ch << ", \"f_px\": " << cam.f_px << ", \"cam_z\": " << cam.cam_z
           << ", \"sx\": " << cam.sx << ", \"sy\": " << cam.sy << ", \"scale\": " << scale
           << ", \"n_sites\": " << sites.size() << ", \"n_objects\": " << obj_index
           << ", \"maps\": {\"site\": \"u2\", \"obj\": \"u4\", \"class\": \"u1\", \"depth\": \"f4\", \"normal\": \"f4x3\"}}\n";
    };

    std::string base = cfg.s("output.basename", "");
    if (base.empty()) {
        std::stringstream b;
        b << "raster_" << std::setfill('0') << std::setw(3) << cfg.i("canopy.age") << "_" << std::setfill('0') << std::setw(7) << seed;
        base = b.str();
    }

    // Batch mode: every site alone, cropped, in this one process. A candidate sweep needs
    // hundreds of single plants; building them in one process amortises the start-up and asset
    // loading that otherwise dominate (about a second per plant when each is its own process).
    if (cfg.i("raster.each_site", 0)) {
        size_t n_written = 0;
        for (size_t k = 0; k < sites.size(); k++) {
            if (!draw[k]) continue;
            RasterMaps mk;
            mk.init(cam.W, cam.H);
            draw_site(mk, k);
            write_maps(mk, base + "_s" + std::to_string(k), true);
            n_written++;
        }
        const auto t2 = std::chrono::steady_clock::now();
        const auto ms = [](auto a, auto b) { return std::chrono::duration_cast<std::chrono::milliseconds>(b - a).count(); };
        std::cout << "DIAG raster build_ms=" << ms(t0, t1) << " each_site_ms=" << ms(t1, t2) << " sites_written=" << n_written
                  << " primitives=" << context.getPrimitiveCount() << " W=" << cam.W << " H=" << cam.H << std::endl;
        std::cout << "wrote " << out << base << "_s*" << std::endl;
        return 0;
    }

    for (size_t k = 0; k < sites.size(); k++) {
        if (!draw[k]) continue;
        draw_site(maps, k);
    }
    const auto t2 = std::chrono::steady_clock::now();

    size_t veg = 0, ground_px = 0;
    std::set<uint32_t> visible_leaves, visible_flowers;
    for (size_t p = 0; p < maps.cls.size(); p++) {
        const uint8_t c = maps.cls[p];
        if (c >= 1 && c <= 5) veg++;
        else if (c == 0) ground_px++;
        if (c == 1) visible_leaves.insert(maps.obj[p]);
        else if (c == 2 || c == 3) visible_flowers.insert(maps.obj[p]);
    }
    write_maps(maps, base, cfg.i("raster.crop", 0) != 0);
    // Sidecar for the whole-scene pass: which obj.u32 value each organ was drawn under. Only meaningful
    // alongside these maps, so it is written with them rather than kept anywhere.
    {
        std::ofstream organs(out + base + "_objindex.txt");
        if (!organs) {
            helios_runtime_error("ERROR: cannot open " + out + base + "_objindex.txt for writing.");
        }
        organs << "# helios_objID obj_index\n";
        for (const auto &entry: organ_index_of) organs << entry.first << " " << entry.second << "\n";
    }
    const auto t3 = std::chrono::steady_clock::now();
    const auto ms = [](auto a, auto b) { return std::chrono::duration_cast<std::chrono::milliseconds>(b - a).count(); };
    std::cout << "DIAG raster build_ms=" << ms(t0, t1) << " raster_ms=" << ms(t1, t2) << " write_ms=" << ms(t2, t3)
              << " primitives=" << context.getPrimitiveCount() << " W=" << cam.W << " H=" << cam.H
              << " veg_cover=" << double(veg) / double(maps.cls.size())
              << " ground_frac=" << double(ground_px) / double(maps.cls.size())
              << " leaves=" << n_leaves << " leaves_visible=" << visible_leaves.size()
              << " flowers=" << n_flowers << " flowers_visible=" << visible_flowers.size() << std::endl;
    std::cout << "wrote " << out << base << "_*" << std::endl;
    return 0;
}

// ------------------------------------------------------------------- render ---

int render(const Config &cfg, unsigned seed) {

    Context context;
    context.seedRandomGenerator(seed);
    RadiationModel radiation(&context);
    PlantArchitecture plantarchitecture(&context);
    LeafOptics leafoptics(&context);

    // --- spectra for non-leaf surfaces -------------------------------------
    context.loadXML("plugins/radiation/spectral_data/color_board/DGK_DKK_colorboard.xml", true);
    context.renameGlobalData("ColorReference_DGK_01", "spectrum_white");
    context.renameGlobalData("ColorReference_DGK_05", "spectrum_darkgray");
    context.renameGlobalData("ColorReference_DGK_08", "spectrum_yellow");
    context.renameGlobalData("ColorReference_DGK_17", "spectrum_tan");
    context.loadXML("plugins/radiation/spectral_data/color_board/Calibrite_ColorChecker_Classic_colorboard.xml", true);
    context.renameGlobalData("ColorReference_Calibrite_05", "spectrum_purple");
    context.renameGlobalData("ColorReference_Calibrite_14", "spectrum_green");
    context.renameGlobalData("ColorReference_Calibrite_01", "spectrum_brown");
    context.renameGlobalData("ColorReference_Calibrite_12", "spectrum_amber");
    context.loadXML("plugins/radiation/spectral_data/light_spectral_library.xml", true);
    // Required: without it setCameraSpectralResponse() silently falls back to a
    // FLAT response, which invalidates the colour calibration -- the CCM and the
    // fitted leaf pigments were both solved against the real Basler curves.
    context.loadXML("plugins/radiation/spectral_data/camera_spectral_library.xml", true);
    const std::vector<uint> plantIDs = makeCanopy(cfg, context, plantarchitecture, seed);

    // --- leaf optics from PROSPECT -----------------------------------------
    // Replaces the LI-COR measured library: its reflectance carries a ~0.05
    // additive stray-light offset (R(680)=0.083 while T(680)=0.011), which
    // rendered leaves grey-green. PROSPECT is self-consistent by construction.
    // leaf.optics (2026-09-29): which leaf optics the canopy gets. Only "cowpea" exists -- the PROSPECT parameters of this
    // config, fitted to cowpea -- and it is the default for every species until per-species optics are decided.
    if (cfg.s("leaf.optics", "cowpea") != "cowpea") {
        helios_runtime_error("ERROR (render): leaf.optics '" + cfg.s("leaf.optics") + "' is not available; only 'cowpea' (the config's PROSPECT parameters).");
    }
    LeafOpticsProperties leafprops;
    leafprops.chlorophyllcontent = cfg.f("leaf.chlorophyll");
    leafprops.carotenoidcontent = cfg.f("leaf.carotenoid");
    leafprops.anthocyancontent = cfg.f("leaf.anthocyanin");
    leafprops.numberlayers = cfg.f("leaf.numberlayers");
    leafprops.watermass = cfg.f("leaf.watermass");
    leafprops.drymass = cfg.f("leaf.drymass");
    if (cfg.i("plant.assign_spectra", 1) && cfg.i("leaf.use_prospect", 1)) {
        if (cfg.i("leaf.nitrogen_model", 0) || cfg.f("leaf.chlorophyll_sd", 0.f) > 0.f || cfg.f("leaf.chlorophyll_young_fraction", 1.f) < 1.f) {
            // Nitrogen-driven mode: one spectrum per bin of leaf nitrogen, assigned per leaf from
            // the "leaf_nitrogen_gN_m2" object data written by the nitrogen model above.
            // Cab = N_area * 100 * f_photosynthetic * N_to_Cab_coefficient, so the fixed-spectrum
            // chlorophyll this replaces (leaf.chlorophyll) corresponds to a particular N_area and
            // the population mean should be held there to avoid moving the canopy's median colour.
            LeafOpticsProperties_Nauto nauto;
            nauto.f_photosynthetic = cfg.f("leaf.f_photosynthetic", 0.50f);
            nauto.N_to_Cab_coefficient = cfg.f("leaf.N_to_Cab_coefficient", 0.40f);
            nauto.Car_to_Cab_ratio = cfg.f("leaf.Car_to_Cab_ratio", leafprops.carotenoidcontent / std::max(leafprops.chlorophyllcontent, 1e-6f));
            nauto.numberlayers = leafprops.numberlayers;
            nauto.anthocyancontent = leafprops.anthocyancontent;
            nauto.watermass = leafprops.watermass;
            nauto.drymass = leafprops.drymass;
            nauto.num_bins = uint(cfg.i("leaf.nitrogen_bins", 20));
            leafoptics.run(plantarchitecture.getAllLeafUUIDs(), nauto);

            // Copy each leaf's nitrogen from its object down onto its primitives, so the camera can
            // write a per-pixel map of it. The leaf-nitrogen distribution over LEAVES is not the one
            // that sets image colour -- a nadir camera over a closed canopy sees the newest growth
            // at the top and little of what is beneath it, so what matters is the distribution over
            // VISIBLE PIXELS. Those two are only the same if nothing is occluded.
            for (uint uuid: plantarchitecture.getAllLeafUUIDs()) {
                const uint objID = context.getPrimitiveParentObjectID(uuid);
                if (objID > 0 && context.doesObjectDataExist(objID, "leaf_nitrogen_gN_m2")) {
                    float leaf_N = 0.f;
                    context.getObjectData(objID, "leaf_nitrogen_gN_m2", leaf_N);
                    context.setPrimitiveData(uuid, "leaf_N_map", leaf_N);
                }
            }
            // Nitrogen mode names its spectra per bin, so the fixed "leaf_..._cowpea_leaf" labels
            // the uniform path creates do not exist. The venation blend below still refers to them,
            // and without this the render aborts in RadiationModel::loadSpectralData. Register the
            // population-median spectrum under those names: veins are a fixed yellower blend and do
            // not vary with leaf nitrogen, so the median leaf is the right reference for them.
            std::vector<vec2> median_R, median_T;
            leafoptics.getLeafSpectra(leafprops, median_R, median_T);
            context.setGlobalData("leaf_reflectivity_cowpea_leaf", median_R);
            context.setGlobalData("leaf_transmissivity_cowpea_leaf", median_T);
        } else {
            leafoptics.run(plantarchitecture.getAllLeafUUIDs(), leafprops, "cowpea_leaf");
        }
        // The scanned leaf meshes carry a separate "veins" sub-object. Left with
        // the lamina spectrum the venation disappears; the baseline gave it its
        // own slightly yellower, non-transmitting spectrum.
        if (cfg.i("leaf.use_obj_mesh", 0)) {
            const std::vector<uint> veins = context.filterPrimitivesByData(context.getAllUUIDs(), "object_label", "veins");
            // Venation strength is exposed because it may be over-drawn. SAM finds 1.88x as many
            // leaf objects in the synthetic set as the real one at 1/1.375 the size, and
            // sqrt(1.88) = 1.371 -- the signature of each leaf being split into two pieces, not of
            // leaves being small. A midrib rendered too yellow and too opaque would do exactly
            // that, to a segmenter and to the eye. Setting the fraction to zero leaves the veins
            // with the lamina spectrum and its transmissivity, which is the control.
            const float vein_yellow = cfg.f("leaf.vein_yellow_fraction", 0.15f);
            if (!veins.empty() && vein_yellow > 0.f) {
                radiation.blendSpectra("reflectivity_veins", {"leaf_reflectivity_cowpea_leaf", "spectrum_yellow"},
                                       {1.f - vein_yellow, vein_yellow});
                context.setPrimitiveData(veins, "reflectivity_spectrum", "reflectivity_veins");
                if (cfg.i("leaf.vein_opaque", 1)) {
                    context.clearPrimitiveData(veins, "transmissivity_spectrum");
                }
                std::cout << "DIAG veins_primitives=" << veins.size()
                          << " yellow_fraction=" << vein_yellow
                          << " opaque=" << cfg.i("leaf.vein_opaque", 1) << std::endl;
            }
        }
    } else if (cfg.i("plant.assign_spectra", 1)) {
        radiation.scaleSpectrum("spectrum_green", "reflectivity_leaf_fallback", 0.5);
        context.setPrimitiveData(plantarchitecture.getAllLeafUUIDs(), "reflectivity_spectrum", "reflectivity_leaf_fallback");
    }
    context.setPrimitiveData(plantarchitecture.getAllLeafUUIDs(), "specular_exponent", cfg.f("leaf.specular_exponent"));
    context.setPrimitiveData(plantarchitecture.getAllLeafUUIDs(), "specular_scale", cfg.f("leaf.specular_scale"));

    // stems / peduncles / flowers
    // Stems and petioles are green tissue like the lamina, somewhat lighter and yellower: the leaf's own reflectance blended with a
    // little yellow and scaled. They used to be the colour checker's green patch, which rendered them a saturated lime (C* 62 against
    // a real 36 in the 06-20 frame). Defaults from scripts/twin_stem_colour.py on 06-20 Plot286 (2026-09-15): petiole minus leaf
    // dL* +5.9, da* -2, db* +6 against a real +7.1, +4, +5. stem.candidates "y:s,y:s,..." gives plant k the k-th pair (cyclically).
    auto make_stem_spectrum = [&](const std::string &label, float yellow_fraction, float reflectance_scale) {
        radiation.blendSpectra(label, {"leaf_reflectivity_cowpea_leaf", "spectrum_yellow"}, {1.f - yellow_fraction, yellow_fraction});
        radiation.scaleSpectrum(label, reflectance_scale);
    };
    make_stem_spectrum("reflectivity_stem", cfg.f("stem.yellow_fraction", 0.01f), cfg.f("stem.reflectance_scale", 2.0f));
    std::vector<std::string> stem_labels;
    if (cfg.has("stem.candidates")) {
        std::stringstream list(cfg.s("stem.candidates"));
        std::string pair;
        while (std::getline(list, pair, ',')) {
            const size_t colon = pair.find(':');
            if (colon == std::string::npos) helios_runtime_error("ERROR (stem.candidates): expected y:s pairs, got '" + pair + "'.");
            const std::string label = "reflectivity_stem_" + std::to_string(stem_labels.size());
            make_stem_spectrum(label, std::stof(pair.substr(0, colon)), std::stof(pair.substr(colon + 1)));
            std::cout << "DIAG stem_candidate " << stem_labels.size() << " yellow_fraction=" << pair.substr(0, colon) << " reflectance_scale=" << pair.substr(colon + 1) << std::endl;
            stem_labels.push_back(label);
        }
    }
    if (context.randu() < cfg.f("flower.white_flower_prob")) {
        radiation.scaleSpectrum("spectrum_white", "reflectivity_flower_open", 0.5);
    } else {
        radiation.blendSpectra("reflectivity_flower_open", {"spectrum_purple", "spectrum_white"}, {0.7, 0.3});
        radiation.scaleSpectrum("reflectivity_flower_open", 0.8f);
    }
    radiation.blendSpectra("reflectivity_flower_closed", {"spectrum_yellow", "spectrum_green"}, {0.35, 0.65});
    radiation.scaleSpectrum("reflectivity_flower_closed", 0.7);
    radiation.blendSpectra("reflectivity_pods", {"spectrum_green", "spectrum_yellow"}, {0.8, 0.2});
    radiation.scaleSpectrum("reflectivity_pods", 0.5);

    if (cfg.i("plant.assign_spectra", 1))
    for (size_t k = 0; k < plantIDs.size(); k++) {
        const uint id = plantIDs[k];
        const std::string stem_label = stem_labels.empty() ? "reflectivity_stem" : stem_labels[k % stem_labels.size()];
        context.setPrimitiveData(context.getObjectPrimitiveUUIDs(plantarchitecture.getPlantPetioleObjectIDs(id)),
                                 "reflectivity_spectrum", stem_label);
        context.setPrimitiveData(context.getObjectPrimitiveUUIDs(plantarchitecture.getPlantInternodeObjectIDs(id)),
                                 "reflectivity_spectrum", stem_label);
        context.setPrimitiveData(context.getObjectPrimitiveUUIDs(plantarchitecture.getPlantPeduncleObjectIDs(id)),
                                 "reflectivity_spectrum", stem_label);
        context.setPrimitiveData(context.getObjectPrimitiveUUIDs(plantarchitecture.getPlantFruitObjectIDs(id)),
                                 "reflectivity_spectrum", "reflectivity_pods");
        for (uint objID: plantarchitecture.getPlantFlowerObjectIDs(id)) {
            const std::vector<uint> uuid = context.getObjectPrimitiveUUIDs(objID);
            const bool open = context.doesObjectDataExist(objID, "openflowerID");
            context.setPrimitiveData(uuid, "reflectivity_spectrum",
                                     open ? "reflectivity_flower_open" : "reflectivity_flower_closed");
        }
        context.setPrimitiveData(plantarchitecture.getAllPlantUUIDs(id), "plantID", int(id));
    }

    // --- ground -------------------------------------------------------------
    // Ground subdivision sets the resolution of shadows on the soil: the camera reads radiance per
    // primitive, so a shadow edge is quantised to the sub-patch size. 250 x 250 over 3 m is 1.2 cm,
    // about 14 pixels at the rover camera's ground sampling distance, which is what the blocky
    // shadow halos around seedlings are. A twin of one frame wants 3-4 mm (750-1000).
    const int ground_subdiv = cfg.i("scene.ground_subdiv", 250);
    // The tile is the bed by default. A camera tilted off nadir sees past its edge into empty space, so scene.ground_size_x/y
    // enlarge it; the subdivision count grows with it so the patch size, which quantises the shadows, stays put.
    const vec2 ground_size = make_vec2(cfg.f("scene.ground_size_x", 3.f), cfg.f("scene.ground_size_y", 3.048f));
    const int2 ground_div = make_int2(std::max(1, int(std::lround(ground_subdiv * ground_size.x / 3.f))),
                                      std::max(1, int(std::lround(ground_subdiv * ground_size.y / 3.048f))));
    std::vector<uint> ground = context.addTile(make_vec3(0, 0, -0.01), ground_size, nullrotation,
                                               ground_div, make_RGBcolor(0.45, 0.36, 0.28));
    context.setPrimitiveData(ground, "twosided_flag", uint(0));
    context.loadXML(cfg.s("paths.soil_spec_xml", syn2realPath(cfg, "xml/soil_spec.xml")).c_str(), true);
    // Which of the four library soils. Drawn per scene for the distribution task; a twin of one
    // frame names it (soil.spectrum_index 0-3) so the soil is a fitted choice, not a lottery.
    const int soil_index = cfg.i("soil.spectrum_index", -1);
    context.renameGlobalData(("soil_" + std::to_string(soil_index >= 0 ? soil_index : context.randu(0, 4))).c_str(), "soil_reflectivity");
    std::cout << "DIAG soil_index=" << soil_index << std::endl;
    // Soil brightness. The soil_spec library sits at 0.37-0.50 reflectance, which
    // renders at L~99 against a measured real soil L of 59.6. Bright soil gaps
    // against dark canopy are the main driver of the excess luminance spread
    // (L_std 23.5 vs a real 15.5) that survives the pedestal/knee fix.
    const float soil_scale = cfg.f("soil.reflectance_scale", 1.0f);
    if (soil_scale != 1.0f) {
        radiation.scaleSpectrum("soil_reflectivity", soil_scale);
    }
    // The real frame's soil as the ground albedo (twin/soil.py writes the map): per-band
    // reflectance sampled at each ground sub-patch centre, in place of the library spectrum.
    // Format: int32 res_x, res_y; float32 x0, y0, dx, dy; float32 RGB row-major, y outer.
    if (cfg.has("scene.soil_albedo_map")) {
        std::ifstream f(cfg.s("scene.soil_albedo_map"), std::ios::binary);
        if (!f) helios_runtime_error("ERROR (render): cannot open scene.soil_albedo_map " + cfg.s("scene.soil_albedo_map"));
        int32_t res_x = 0, res_y = 0;
        float x0 = 0, y0 = 0, dx = 1, dy = 1;
        f.read(reinterpret_cast<char *>(&res_x), 4);
        f.read(reinterpret_cast<char *>(&res_y), 4);
        f.read(reinterpret_cast<char *>(&x0), 4);
        f.read(reinterpret_cast<char *>(&y0), 4);
        f.read(reinterpret_cast<char *>(&dx), 4);
        f.read(reinterpret_cast<char *>(&dy), 4);
        std::vector<float> amap(size_t(res_x) * res_y * 3);
        f.read(reinterpret_cast<char *>(amap.data()), std::streamsize(amap.size() * sizeof(float)));
        if (!f) helios_runtime_error("ERROR (render): scene.soil_albedo_map is truncated.");
        // The map's absolute level is an assumption (twin/soil.py normalizes its median to 0.04), and it sets how bright the soil
        // is against the canopy. scene.soil_albedo_scale multiplies it, fitted per frame so the rendered soil matches the real one
        // at the exposure that matches real foliage.
        const float albedo_scale = cfg.f("scene.soil_albedo_scale", 1.0f);
        auto mirror_index = [](int i, int n) {
            if (n <= 1) return 0;
            const int period = 2 * n;
            const int m = ((i % period) + period) % period;
            return m < n ? m : period - 1 - m;
        };
        const char *band_names[3] = {"reflectivity_red", "reflectivity_green", "reflectivity_blue"};
        for (uint u: ground) {
            vec3 c(0, 0, 0);
            const std::vector<vec3> verts = context.getPrimitiveVertices(u);
            for (const vec3 &v: verts) c = c + v;
            c = c / float(verts.size());
            // Mirror-tile beyond the map. Clamping repeated the edge pixel outward, which reads as a blurry band radiating
            // from the bed; mirroring continues the soil across the boundary without a seam.
            const int ix = mirror_index(int(std::floor((c.x - x0) / dx)), res_x);
            const int iy = mirror_index(int(std::floor((c.y - y0) / dy)), res_y);
            for (int b = 0; b < 3; b++) {
                context.setPrimitiveData(u, band_names[b], std::min(albedo_scale * amap[(size_t(iy) * res_x + ix) * 3 + b], 1.f));
            }
        }
        std::cout << "DIAG soil_albedo_map=" << cfg.s("scene.soil_albedo_map") << " scale=" << albedo_scale << " res=" << res_x << "x" << res_y
                  << " patches=" << ground.size() << std::endl;
    } else {
        context.setPrimitiveData(ground, "reflectivity_spectrum", "soil_reflectivity");
    }
    // A neutral reference patch (the DGK white-balance card's white, spectrally near-flat) for checking
    // what colour the rig lighting and camera chain give a grey surface. Off unless a size is given.
    if (cfg.f("scene.grey_patch_size", 0.f) > 0.f) {
        const float patch_size = cfg.f("scene.grey_patch_size");
        std::vector<uint> patch = context.addTile(make_vec3(cfg.f("scene.grey_patch_x", 0.f), cfg.f("scene.grey_patch_y", 0.f), 0.03f), make_vec2(patch_size, patch_size),
                                                  nullrotation, make_int2(4, 4));
        context.setPrimitiveData(patch, "reflectivity_spectrum", "spectrum_white");
        context.setPrimitiveData(patch, "twosided_flag", uint(0));
        context.setPrimitiveData(patch, "patchID", int(1));
        std::cout << "DIAG grey_patch size=" << patch_size << std::endl;
    }
    // Tag the ground so an exact soil mask can be written alongside the image. Canopy cover was
    // previously inferred from pixel colour, which is unreliable in both directions: Excess Green
    // is broken by the colour matrix's negative blue row, and even a CIELAB a* test misclassifies
    // this soil, which renders at a* -5.9 (green side) against a real soil's +2.4. On a frame with
    // five plants and a third of the field of view bare, colour-based cover read 0.90. The renderer
    // knows exactly which pixels are ground, so ask it rather than guess.
    context.setPrimitiveData(ground, "groundID", int(1));

    // --- T4 rover body ------------------------------------------------------
    // The rover was dropped in an earlier rewrite of this file. It matters: the
    // body sits between the lights and the canopy, occluding part of the upper
    // hemisphere and shading the plot. Without it the canopy is lit from a much
    // more open sky and the specular response reads like open sunlight rather
    // than a shrouded LED rig.
    std::vector<uint> UUIDs_T4;
    if (cfg.i("scene.load_rover", 1)) {
        context.loadXML(syn2realPath(cfg, "T4_body_reflectance.xml").c_str(), true);
        UUIDs_T4 = context.loadOBJ(syn2realPath(cfg, "obj/T4rover_highres.obj").c_str(),
                                   make_vec3(0, 0, -0.05), 0, nullrotation, RGB::black);
        // Rover reflectance scales. The body sits within a metre of the LED rig and renders far
        // brighter than the real rails: measured on the 06-20 frame, rendered rover pixels were
        // 5.5x the real ones in linear radiance (L* 70 against 32) with the same hue, so the
        // twin passes 0.17x the earlier project's values (frame 0.22, fender 0.13, tyre 0.17).
        radiation.scaleSpectrum("T4_fender_reflectance", cfg.f("scene.rover_fender_scale", 0.75f));
        radiation.scaleSpectrum("T4_frame_reflectance", cfg.f("scene.rover_frame_scale", 1.3f));
        radiation.scaleSpectrum("spectrum_darkgray", "T4_tyre_reflectance", cfg.f("scene.rover_tyre_scale", 1.0f));
        // The model's parts are named Tire_LF..RR (rubber), Wheel_LF..RR (bare-metal rims), Fender, Shade, Top, Main_body_in/out.
        // The tyre spectrum used to be matched against "Tyre_wheel", a label this OBJ does not contain, so nothing ever received
        // it and every part but the fender rendered as olive frame paint -- rims included, which is much of why the rig reads flat.
        radiation.scaleSpectrum("spectrum_white", "T4_metal_reflectance", cfg.f("scene.rover_wheel_scale", 0.35f));
        context.setPrimitiveData(UUIDs_T4, "reflectivity_spectrum", "T4_frame_reflectance");
        int n_tyre = 0, n_wheel = 0, n_fender = 0;
        for (uint u: UUIDs_T4) {
            if (!context.doesPrimitiveDataExist(u, "object_label")) continue;
            std::string lab;
            context.getPrimitiveData(u, "object_label", lab);
            if (lab.rfind("Tire", 0) == 0 || lab == "Tyre_top") {
                context.setPrimitiveData(u, "reflectivity_spectrum", "T4_tyre_reflectance");
                n_tyre++;
            } else if (lab.rfind("Wheel", 0) == 0) {
                context.setPrimitiveData(u, "reflectivity_spectrum", "T4_metal_reflectance");
                n_wheel++;
            } else if (lab == "Fender") {
                context.setPrimitiveData(u, "reflectivity_spectrum", "T4_fender_reflectance");
                n_fender++;
            }
        }
        std::cout << "DIAG rover_materials tyre=" << n_tyre << " wheel=" << n_wheel << " fender=" << n_fender << std::endl;
        // The frame and fenders are aluminium: dark in the mean, with strong highlights. Their diffuse reflectance was scaled
        // to the real rover's MEAN brightness, so with no specular at all they render flat and dead. Off by default so earlier
        // renders reproduce; the tyres are rubber and stay matte.
        const float rover_specular = cfg.f("scene.rover_specular_scale", 0.f);
        if (rover_specular > 0.f) {
            const float rover_exponent = cfg.f("scene.rover_specular_exponent", 150.f);
            for (uint u: UUIDs_T4) {
                std::string lab;
                if (context.doesPrimitiveDataExist(u, "object_label")) context.getPrimitiveData(u, "object_label", lab);
                if (lab.rfind("Tire", 0) == 0 || lab == "Tyre_top") continue; // rubber stays matte
                context.setPrimitiveData(u, "specular_exponent", rover_exponent);
                context.setPrimitiveData(u, "specular_scale", rover_specular);
            }
            std::cout << "DIAG rover_specular scale=" << rover_specular << " exponent=" << rover_exponent << std::endl;
        }

        // Tag the rover so an exact mask can be written alongside the image.
        // Two attempts to detect it from pixels failed: a texture heuristic
        // rejected smooth bright soil along with painted metal, and an explicit
        // crop region still let structural members into tile edges. The renderer
        // knows precisely where it is, so ask it.
        context.setPrimitiveData(UUIDs_T4, "roverID", int(1));
        std::cout << "DIAG rover_primitives=" << UUIDs_T4.size() << std::endl;
    }

    // --- lighting -----------------------------------------------------------
    const float z_lights = 1.6f;
    const float light_scale = cfg.f("light.flux_scale");
    // Source SIZE, not source flux, controls shadow hardness. The rig is modelled
    // as six 0.1 x 0.08 m rectangles at 1.6 m, which are nearly point sources at
    // that distance and cast hard-edged shadows: 19.7 % of rendered pixels fall
    // below L=10 against 0.6 % in the real imagery. Neither scattering depth
    // (leaves absorb too strongly in the visible for 2nd/3rd bounces to matter)
    // nor side-light ratio moved this at all. Enlarging the emitters softens the
    // penumbra, which is the physical mechanism actually available.
    const float ls = cfg.f("light.source_scale", 1.0f);
    std::vector<uint> overhead, side;
    overhead.push_back(radiation.addRectangleRadiationSource(make_vec3(-0.2, 0.123, z_lights), make_vec2(0.1f * ls, 0.08f * ls), make_vec3(M_PI, deg2rad(-10), 0)));
    overhead.push_back(radiation.addRectangleRadiationSource(make_vec3(0.2, 0.123, z_lights), make_vec2(0.1f * ls, 0.08f * ls), make_vec3(M_PI, deg2rad(10), 0)));
    overhead.push_back(radiation.addRectangleRadiationSource(make_vec3(-0.4, 0.18, z_lights), make_vec2(0.1f * ls, 0.08f * ls), make_vec3(M_PI + deg2rad(10), 0, 0)));
    overhead.push_back(radiation.addRectangleRadiationSource(make_vec3(0.4, 0.18, z_lights), make_vec2(0.1f * ls, 0.08f * ls), make_vec3(M_PI + deg2rad(10), 0, 0)));
    overhead.push_back(radiation.addRectangleRadiationSource(make_vec3(-0.5, -0.1, z_lights), make_vec2(0.1f * ls, 0.08f * ls), make_vec3(M_PI + deg2rad(-10), 0, 0)));
    overhead.push_back(radiation.addRectangleRadiationSource(make_vec3(0.5, -0.1, z_lights), make_vec2(0.1f * ls, 0.08f * ls), make_vec3(M_PI + deg2rad(-10), 0, 0)));
    side.push_back(radiation.addRectangleRadiationSource(make_vec3(-0.65, -0.1, 0.75), make_vec2(0.35f * ls, 0.02f * ls), make_vec3(0, 0.5 * M_PI, 0.1 * M_PI)));
    side.push_back(radiation.addRectangleRadiationSource(make_vec3(0.65, 0.1, 0.75), make_vec2(0.35f * ls, 0.02f * ls), make_vec3(0, -0.5 * M_PI, 0.1 * M_PI)));

    float total_flux = 0;
    std::vector<uint> all_lights = overhead;
    all_lights.insert(all_lights.end(), side.begin(), side.end());
    for (uint id: all_lights) {
        std::vector<vec2> spec;
        context.getGlobalData("CREE_XLamp_XHP70p2_6500K", spec);
        const float flux = radiation.integrateSpectrum(spec, 300, 2500);
        radiation.setSourceSpectrum(id, "CREE_XLamp_XHP70p2_6500K");
        radiation.setSourceSpectrumIntegral(id, flux);
        total_flux += flux;
    }
    std::cout << "DIAG total_flux=" << total_flux << " n_lights=" << all_lights.size() << std::endl;
    const uint ID_sun = radiation.addCollimatedRadiationSource(make_vec3(0.2, 0, 0.9));
    // Without a spectrum the sun's camera signal is normalized by the response integral (weight 1 for a white surface),
    // while the LEDs' is weighted by the integral of spectrum x response over the spectrum (about 0.05 here), so the same
    // band flux reads roughly 20x brighter from the sun. Giving the sun a spectrum puts both on the same footing.
    if (cfg.has("light.sun_spectrum")) {
        context.loadXML("plugins/radiation/spectral_data/solar_spectrum_ASTMG173.xml", true);
        radiation.setSourceSpectrum(ID_sun, cfg.s("light.sun_spectrum"));
        std::cout << "DIAG sun_spectrum=" << cfg.s("light.sun_spectrum") << std::endl;
    }

    radiation.addRadiationBand("red");
    radiation.disableEmission("red");
    for (uint id: overhead) radiation.setSourceFlux(id, "red", total_flux * light_scale);
    for (uint id: side) radiation.setSourceFlux(id, "red", total_flux * cfg.f("light.side_ratio") * light_scale);
    radiation.setSourceFlux(ID_sun, "red", cfg.f("light.sun_flux"));
    // Isotropic diffuse fill.
    //
    // The scene was lit only by eight small rectangle LEDs plus a weak collimated
    // sun, so the canopy interior received almost no light: 19.7 % of rendered
    // pixels fall below L=10 against 0.6 % in the real imagery, and that -- not
    // the colour matrix -- is what inflates the luminance spread (L_std 29.8 vs a
    // real 15.5). Rolling the CCM off in the shadows changed nothing, which is
    // what ruled the matrix out. Real field scenes always carry diffuse skylight
    // filling the shadows; this restores it.
    radiation.setDiffuseRadiationFlux("red", cfg.f("light.diffuse_flux", 0.f));
    radiation.setScatteringDepth("red", cfg.i("light.scattering_depth"));
    radiation.copyRadiationBand("red", "green");
    radiation.copyRadiationBand("red", "blue");
    radiation.setDiffuseRadiationFlux("green", cfg.f("light.diffuse_flux", 0.f));
    radiation.setDiffuseRadiationFlux("blue", cfg.f("light.diffuse_flux", 0.f));
    if (cfg.i("light.periodic_boundary", 1)) radiation.enforcePeriodicBoundary("xy");
    const std::vector<std::string> bands = {"red", "green", "blue"};

    // --- camera -------------------------------------------------------------
    // Geometry pinned from the datasheet and rig measurements: PYTHON 5000
    // sensor 12.44 x 9.83 mm behind a 12 mm lens gives HFOV 54.8 / VFOV 44.5.
    // FOV_aspect_ratio is deliberately NOT set -- it is deprecated and now
    // derived from the resolution to keep pixels square.
    CameraProperties cam;
    cam.camera_resolution = make_int2(cfg.i("camera.resolution_x"), cfg.i("camera.resolution_y"));
    cam.focal_plane_distance = cfg.f("camera.focal_plane_distance");
    cam.lens_diameter = cfg.f("camera.lens_diameter");
    cam.HFOV = cfg.f("camera.hfov");
    // Exposure/white-balance are applied by the renderer itself. They must be
    // controllable: the CCM was solved assuming white balance = normalize by the
    // response to a white diffuser, and if the renderer's own convention differs
    // the matrix is being applied on top of the wrong input.
    cam.exposure = cfg.s("camera.exposure", "auto");
    // Target median luminance for auto exposure. Helios defaults to 0.18 -- the middle-grey
    // convention, which assumes a scene of grey-card reflectance; a canopy viewed from above is
    // darker, and 0.18 rendered foliage 5 L* units lighter than the real imagery.
    //
    // Drawn per scene rather than fixed. The real set spans L* 39-57 across sessions and weather;
    // a single value reproduces the correct centre with none of that spread, and the objective
    // scores an unreachable real mode as a failure while charging nothing for extra width.
    {
        const float lo = cfg.f("camera.exposure_target_min", 0.15f);
        const float hi = cfg.f("camera.exposure_target_max", 0.15f);
        cam.exposure_target = (hi > lo) ? context.randu(lo, hi) : lo;
        std::cout << "DIAG exposure_target=" << cam.exposure_target << std::endl;
    }
    cam.white_balance = cfg.s("camera.white_balance", "auto");
    // Camera position. Nadir at camera.height by default; camera.tilt_deg swings it off nadir on a sphere of that radius about the
    // bed centre, along the azimuth camera.tilt_azimuth_deg (0 = toward +x, across the rows), still looking at the bed centre.
    const float cam_z = cfg.f("camera.height");
    // camera.orbit_radius_m is the distance from the bed centre when tilting: lowering it walks the camera down and in, so a
    // tilted view clears the rig instead of running into it. Defaults to the nadir height.
    const float orbit_radius = cfg.f("camera.orbit_radius_m", cam_z);
    const float tilt = deg2rad(cfg.f("camera.tilt_deg", 0.f));
    const float tilt_azimuth = deg2rad(cfg.f("camera.tilt_azimuth_deg", 0.f));
    const vec3 camera_position = make_vec3(orbit_radius * std::sin(tilt) * std::cos(tilt_azimuth), orbit_radius * std::sin(tilt) * std::sin(tilt_azimuth), orbit_radius * std::cos(tilt));
    if (tilt != 0.f || orbit_radius != cam_z) {
        std::cout << "DIAG camera_tilt deg=" << cfg.f("camera.tilt_deg", 0.f) << " radius_m=" << orbit_radius << " azimuth_deg=" << cfg.f("camera.tilt_azimuth_deg", 0.f)
                  << " position=" << camera_position.x << "," << camera_position.y << "," << camera_position.z << std::endl;
    }
    radiation.addRadiationCamera("camA", bands, camera_position, make_vec3(0, 0, 0),
                                 cam, cfg.i("camera.samples"));
    radiation.setCameraSpectralResponse("camA", "red", "Basler_acA2500-20gc_red");
    radiation.setCameraSpectralResponse("camA", "green", "Basler_acA2500-20gc_green");
    radiation.setCameraSpectralResponse("camA", "blue", "Basler_acA2500-20gc_blue");

    // --- run ----------------------------------------------------------------
    // The camera reads radiance per primitive, so shadow edges and shading are stepped at the
    // facet scale (a leaf's sub-patches, the ground tile's 1.2 cm patches). Flux smoothing averages
    // the flux onto shared vertices and interpolates across each facet, which removes the steps;
    // the crease angle keeps genuine edges. Off unless a crease angle is given.
    if (cfg.has("camera.flux_smoothing")) {
        radiation.enableCameraFluxSmoothing(cfg.f("camera.flux_smoothing"));
        std::cout << "DIAG flux_smoothing crease_deg=" << cfg.f("camera.flux_smoothing") << std::endl;
    }
    radiation.updateGeometry();
    radiation.runBand(bands);
    {
        std::vector<float> px;
        if (context.doesGlobalDataExist("camera_camA_red")) {
            context.getGlobalData("camera_camA_red", px);
            double mn = 1e30, mx = -1e30; int nan = 0;
            for (float v: px) { if (std::isnan(v)) nan++; else { mn = std::min<double>(mn, (double)v); mx = std::max<double>(mx, (double)v);} }
            std::cout << "DIAG camera red: n=" << px.size() << " nan=" << nan
                      << " min=" << mn << " max=" << mx << std::endl;
        } else { std::cout << "DIAG camera_camA_red global data missing" << std::endl; }
    }

    // Raw linear camera radiance, before any of the post-processing below. Everything from the
    // white balance onward is a per-pixel function of these three channels, so dumping them lets
    // the whole camera chain -- exposure, white balance, colour matrix, tone curve, noise, blur,
    // JPEG quality -- be re-evaluated in seconds without touching the ray tracer. Pair it with
    // camera.exposure=manual so the dump really is raw: auto-exposure is applied inside runBand().
    //
    // Note the EXR writer flips horizontally only, while writeCameraImage() flips both axes; the
    // Python replica accounts for the difference.
    if (cfg.i("output.write_exr", 0)) {
        std::filesystem::create_directories(cfg.s("output.folder"));
        std::stringstream raw_base;
        raw_base << plantSpecies(cfg) << "_" << std::setfill('0') << std::setw(3) << cfg.i("canopy.age")
                 << "_" << std::setfill('0') << std::setw(7) << seed << "_raw";
        radiation.writeCameraImageDataEXR("camA", bands, raw_base.str(), cfg.s("output.folder"));
        std::cout << "DIAG wrote_exr=" << raw_base.str() << ".exr"
                  << " exposure_mode=" << cfg.s("camera.exposure", "auto") << std::endl;
    }

    // Colour correction solved from the SpyderCHECKR frame. This is the ISP stage
    // Helios does not otherwise model; without it rendered foliage cannot reach
    // the real G/B ratio for ANY leaf pigment combination.
    // --- white balance, applied exactly once, illuminant-aware ---------------
    //
    // Helios' own white balance derives its factors from the camera response
    // curves ALONE, ignoring the illuminant, and it was being applied twice.
    // Setting camera.white_balance=off stopped the double application but took
    // it to ZERO, not one -- so the renderer was emitting raw camera signal in
    // which a WHITE surface already sits at G/B 1.598. The colour matrix was
    // fitted on white-balanced predictions, so it received input roughly 1.6x
    // too green and its blue row (which clamps at G/B ~1.70) collapsed to zero.
    //
    // Correct factors neutralise a white surface UNDER THIS LIGHT: 1 / integral
    // of (source x camera response) per channel, normalised on green.
    if (cfg.i("post.white_balance", 1)) {
        auto integ = [&](const std::string &resp) {
            std::vector<vec2> Q, Lsrc;
            context.getGlobalData(resp.c_str(), Q);
            context.getGlobalData("CREE_XLamp_XHP70p2_6500K", Lsrc);
            double acc = 0;
            for (size_t i = 1; i < Q.size(); i++) {
                const float lam = Q[i].x;
                if (lam < 350 || lam > 1100) continue;
                float Lv = 0; // sample the source at this wavelength
                for (size_t j = 1; j < Lsrc.size(); j++) {
                    if (Lsrc[j].x >= lam) {
                        const float t = (lam - Lsrc[j - 1].x) / std::max(Lsrc[j].x - Lsrc[j - 1].x, 1e-6f);
                        Lv = Lsrc[j - 1].y + t * (Lsrc[j].y - Lsrc[j - 1].y);
                        break;
                    }
                }
                acc += double(Lv) * Q[i].y * (Q[i].x - Q[i - 1].x);
            }
            return acc;
        };
        const double ir = integ("Basler_acA2500-20gc_red");
        const double ig = integ("Basler_acA2500-20gc_green");
        const double ib = integ("Basler_acA2500-20gc_blue");
        if (ir > 0 && ig > 0 && ib > 0) {
            const float wr = float(ig / ir), wg = 1.f, wb = float(ig / ib);
            std::cout << "DIAG wb_factors R=" << wr << " G=" << wg << " B=" << wb << std::endl;
            const char *bands3[3] = {"red", "green", "blue"};
            const float wf[3] = {wr, wg, wb};
            for (int c = 0; c < 3; c++) {
                std::vector<float> d = radiation.getCameraPixelData("camA", bands3[c]);
                for (float &v: d) v *= wf[c];
                radiation.setCameraPixelData("camA", bands3[c], d);
            }
        }
    }

    const std::string ccm = cfg.s("post.ccm_file", "");
    if (!ccm.empty()) {
        // Shadow-protected colour correction.
        //
        // The matrix separates channels using large negative off-diagonals. Applied
        // flat across the whole tonal range it drives dark pixels below zero, where
        // lin_to_srgb clamps them to pure black -- 28.6 % of pixels below L=10
        // against a real 0.6 %. Lifting them afterwards with a black-level pedestal
        // fixes the histogram but desaturates the shadows, which then fail the
        // excess-green test and drops apparent canopy cover from 0.96 to 0.82.
        //
        // Real ISPs solve this by rolling the matrix off toward identity as
        // luminance falls, so shadows stay neutral-ish instead of going negative.
        // That preserves mid-tone chroma (which the colour match depends on) while
        // never producing a negative to clamp.
        float M[3][3];
        {
            std::ifstream f(ccm);
            if (!f) helios_runtime_error("cannot open CCM file: " + ccm);
            std::string line;
            int row = 0;
            while (std::getline(f, line) && row < 3) {
                const size_t a = line.find("<row>"), b = line.find("</row>");
                if (a == std::string::npos || b == std::string::npos) continue;
                std::istringstream ss(line.substr(a + 5, b - a - 5));
                ss >> M[row][0] >> M[row][1] >> M[row][2];
                row++;
            }
            if (row != 3) helios_runtime_error("CCM file did not contain 3 rows: " + ccm);
        }
        const float ylo = cfg.f("post.ccm_shadow_lo", 0.0f);
        const float yhi = cfg.f("post.ccm_shadow_hi", 0.0f);
        // Matrix strength: blend toward identity. The matrix is the camera's own,
        // measured from a colour board, and at full strength it overshoots here --
        // which means the render's PRE-correction colour still differs from what
        // the real camera saw. Until that is fixed at source this is an empirical
        // knob, not a principled one, and it is labelled as such.
        const float alpha = cfg.f("post.ccm_strength", 1.0f);
        for (int r = 0; r < 3; r++)
            for (int c = 0; c < 3; c++)
                M[r][c] = alpha * M[r][c] + (1.f - alpha) * (r == c ? 1.f : 0.f);
        std::vector<float> R = radiation.getCameraPixelData("camA", "red");
        std::vector<float> G = radiation.getCameraPixelData("camA", "green");
        std::vector<float> B = radiation.getCameraPixelData("camA", "blue");
        for (size_t i = 0; i < R.size(); i++) {
            const float r = R[i], g = G[i], b = B[i];
            float a = 1.f;
            if (yhi > ylo) {
                const float Y = 0.2126f * r + 0.7152f * g + 0.0722f * b;
                a = (Y - ylo) / (yhi - ylo);
                a = a < 0.f ? 0.f : (a > 1.f ? 1.f : a);
                a = a * a * (3.f - 2.f * a); // smoothstep
            }
            const float cr = M[0][0] * r + M[0][1] * g + M[0][2] * b;
            const float cg = M[1][0] * r + M[1][1] * g + M[1][2] * b;
            const float cb = M[2][0] * r + M[2][1] * g + M[2][2] * b;
            R[i] = std::fmaxf(0.f, a * cr + (1.f - a) * r);
            G[i] = std::fmaxf(0.f, a * cg + (1.f - a) * g);
            B[i] = std::fmaxf(0.f, a * cb + (1.f - a) * b);
        }
        radiation.setCameraPixelData("camA", "red", R);
        radiation.setCameraPixelData("camA", "green", G);
        radiation.setCameraPixelData("camA", "blue", B);
        std::cout << "applied CCM (shadow rolloff " << ylo << ".." << yhi << "): " << ccm << std::endl;
    }
    // Black-level pedestal and highlight rolloff.
    //
    // The colour-correction matrix has strong negative off-diagonals (that is how
    // it separates the channels). Applied across the full dynamic range it drives
    // dark pixels below zero, where lin_to_srgb's fmaxf(0,v) clamps them to pure
    // black -- 2.2 % of pixels, against 0.00 % in the real imagery, and it doubled
    // the luminance spread (L_std 27 vs a real 15.5). A real sensor cannot produce
    // a true zero: it has a black-level offset and a noise floor. The pedestal
    // restores that floor; the rolloff softens the top end, which was clipping on
    // the bright soil gaps (2.3 % of pixels at >=250 vs 0.09 % real).
    {
        const float pedestal = cfg.f("post.black_level", 0.0f);
        const float knee = cfg.f("post.highlight_knee", 0.0f);
        if (pedestal > 0.f || knee > 0.f) {
            std::vector<float> R = radiation.getCameraPixelData("camA", "red");
            std::vector<float> G = radiation.getCameraPixelData("camA", "green");
            std::vector<float> B = radiation.getCameraPixelData("camA", "blue");
            for (size_t i = 0; i < R.size(); i++) {
                float r = std::fmaxf(0.f, R[i]), g = std::fmaxf(0.f, G[i]), b = std::fmaxf(0.f, B[i]);
                if (knee > 0.f) {
                    auto roll = [&](float v) { return v > knee ? knee + (v - knee) / (1.f + (v - knee) / knee) : v; };
                    r = roll(r); g = roll(g); b = roll(b);
                }
                if (pedestal > 0.f) {
                    // Lift LUMINANCE, not each channel independently.
                    //
                    // Adding a constant to R, G and B alike moves every colour toward
                    // grey. Applied at the strength needed to match the real shadow
                    // floor it desaturated a fifth of the image, and those pixels then
                    // failed the excess-green test -- apparent canopy cover fell from
                    // 0.96 to 0.82. Scaling all three channels by the same factor
                    // raises luminance while leaving channel RATIOS untouched, so hue,
                    // saturation and the excess-green classification all survive.
                    const float Y = 0.2126f * r + 0.7152f * g + 0.0722f * b;
                    const float Yp = pedestal + Y * (1.f - pedestal);
                    const float sc = Y > 1e-6f ? Yp / Y : 0.f;
                    if (Y > 1e-6f) { r *= sc; g *= sc; b *= sc; }
                    else { r = g = b = Yp; }   // true black has no ratio to preserve
                }
                R[i] = r; G[i] = g; B[i] = b;
            }
            radiation.setCameraPixelData("camA", "red", R);
            radiation.setCameraPixelData("camA", "green", G);
            radiation.setCameraPixelData("camA", "blue", B);
        }
    }
    radiation.applyCameraImageCorrections("camA", "red", "green", "blue",
                                          cfg.f("post.saturation", 1.f),
                                          cfg.f("post.brightness", 1.f),
                                          cfg.f("post.contrast", 1.f));

    {
        // Frame-level green cover, computed the same way the Python diagnostic
        // does (excess-green on normalized chromaticity, fixed threshold) so the
        // two numbers are directly comparable.
        const auto &R = radiation.getCameraPixelData("camA", "red");
        const auto &G = radiation.getCameraPixelData("camA", "green");
        const auto &B = radiation.getCameraPixelData("camA", "blue");
        // Must be computed on the sRGB-ENCODED values, i.e. what the JPEG
        // actually contains. Computing excess-green on the linear post-CCM data
        // classifies everything as vegetation, because the CCM deliberately
        // boosts green relative to blue.
        auto srgb = [](float v) { return RadiationCamera::lin_to_srgb(std::fmaxf(0.f, v)); };
        // Vegetation is classified on the CIELAB a* axis, not by Excess Green.
        //
        // ExG normalizes by the channel sum, and the colour matrix applied above has a strongly
        // negative blue row, so it crushes blue and inflates the green fraction of every pixel: a
        // brown soil pixel of linear (0.20, 0.14, 0.09) leaves the matrix at (0.201, 0.141, 0.035)
        // and scores ExG 0.122, comfortably past the 0.05 threshold. Measured on a deliberately
        // sparse canopy (germination 0.10, mostly bare ground) ExG reported 0.974 cover where the
        // true figure is 0.734. a* is the green-magenta axis and does not depend on blue at all.
        auto to_lab_a = [](float r, float g, float b) {
            auto lin = [](float c) { return c <= 0.04045f ? c / 12.92f : std::pow((c + 0.055f) / 1.055f, 2.4f); };
            const float R = lin(r), G = lin(g), B = lin(b);
            // sRGB D65 -> XYZ, then the L*a*b* transfer applied to X and Y.
            const float X = (0.4124f * R + 0.3576f * G + 0.1805f * B) / 0.95047f;
            const float Y = (0.2126f * R + 0.7152f * G + 0.0722f * B);
            auto f = [](float t) { return t > 0.008856f ? std::cbrt(t) : (7.787f * t + 16.f / 116.f); };
            return 500.f * (f(X) - f(Y));
        };
        const float a_threshold = cfg.f("output.veg_a_threshold", -5.f);
        size_t veg = 0;
        for (size_t i = 0; i < R.size(); i++) {
            if (to_lab_a(srgb(R[i]), srgb(G[i]), srgb(B[i])) < a_threshold) veg++;
        }
        std::cout << "DIAG veg_cover=" << double(veg) / double(R.size()) << std::endl;
    }
    {
        size_t nopen = 0, nclosed = 0;
        for (uint id: plantIDs)
            for (uint objID: plantarchitecture.getPlantFlowerObjectIDs(id)) {
                if (context.doesObjectDataExist(objID, "openflowerID")) nopen++;
                else if (context.doesObjectDataExist(objID, "closedflowerID")) nclosed++;
            }
        std::cout << "DIAG flowers_open=" << nopen << " flowers_closed=" << nclosed << std::endl;
    }
    // A unique ID per leaf object, written as a per-pixel map below. This is ground truth for what a leaf looks like
    // in the image: exact, registered to the same pixels SAM sees, and free of any inference. Without it, SAM's masks
    // were being compared against aggregate box statistics, which cannot show whether a mask corresponds to one leaf,
    // half a leaf, or several.
    //
    // Assigned here, for whatever output.write_leaf_ids asks for, rather than inside the nitrogen-driven spectrum
    // branch where it used to sit: a run that gave its leaves one uniform spectrum skipped that branch and wrote a
    // map of zeros without complaint, and every analysis keyed on those IDs was silently reading nothing.
    size_t leaf_objects_identified = 0;
    // output.write_class_ids 1 (I/O addition, 2026-09-29): a per-pixel organ class map, <base>_class, with the label
    // rasterizer's class.u8 codes -- 1 leaf, 2 open flower, 3 closed flower, 4 stem/petiole/peduncle, 5 fruit (cowpea
    // pod, sorghum panicle, tomato fruit), 0 anything else. Off by default, so existing outputs are unchanged.
    if (cfg.i("output.write_class_ids", 0)) {
        auto tag = [&](const std::vector<uint> &objIDs, int cls) {
            for (uint objID: objIDs) {
                if (context.doesObjectExist(objID)) context.setPrimitiveData(context.getObjectPrimitiveUUIDs(objID), "organClass", cls);
            }
        };
        size_t n_fruit = 0;
        for (uint id: plantIDs) {
            tag(plantarchitecture.getPlantInternodeObjectIDs(id), 4);
            tag(plantarchitecture.getPlantPetioleObjectIDs(id), 4);
            tag(plantarchitecture.getPlantPeduncleObjectIDs(id), 4);
            tag(plantarchitecture.getPlantLeafObjectIDs(id), 1);
            for (uint objID: plantarchitecture.getPlantFlowerObjectIDs(id)) {
                tag({objID}, context.doesObjectDataExist(objID, "openflowerID") ? 2 : 3);
            }
            const std::vector<uint> fruit = plantarchitecture.getPlantFruitObjectIDs(id);
            n_fruit += fruit.size();
            tag(fruit, 5);
        }
        std::cout << "DIAG organ_class fruit_objects=" << n_fruit << std::endl;
    }
    if (cfg.i("output.write_leaf_ids", 0)) {
        int leaf_index = 1;
        std::map<uint, int> object_index;
        for (uint uuid: plantarchitecture.getAllLeafUUIDs()) {
            const uint objID = context.getPrimitiveParentObjectID(uuid);
            if (objID == 0) continue;
            auto it = object_index.find(objID);
            if (it == object_index.end()) {
                it = object_index.emplace(objID, leaf_index++).first;
            }
            context.setPrimitiveData(uuid, "leafObjectID", it->second);
        }
        leaf_objects_identified = object_index.size();
        std::cout << "DIAG leaf_object_ids n=" << leaf_objects_identified << std::endl;
    }

    const std::string out = cfg.s("output.folder");
    // writeCameraImage() requires the directory to exist and errors if it does not. Only the EXR
    // branch created it, so a run with write_exr off computed and printed every diagnostic and then
    // failed at the write, leaving an empty output folder.
    std::filesystem::create_directories(out);
    std::stringstream base;
    base << plantSpecies(cfg) << "_" << std::setfill('0') << std::setw(3) << cfg.i("canopy.age")
         << "_" << std::setfill('0') << std::setw(7) << seed;
    if (cfg.i("output.write_raw", 0)) {
        for (const auto &b: bands) radiation.writeCameraImageData("camA", b, base.str() + "_raw_" + b, out);
    }
    if (cfg.i("scene.load_rover", 1)) {
        radiation.writePrimitiveDataLabelMap("camA", "roverID", base.str() + "_rover", out);
    }
    radiation.writePrimitiveDataLabelMap("camA", "groundID", base.str() + "_ground", out);
    if (cfg.f("scene.grey_patch_size", 0.f) > 0.f) {
        radiation.writePrimitiveDataLabelMap("camA", "patchID", base.str() + "_patch", out);
    }
    if (cfg.i("leaf.nitrogen_model", 0) || cfg.f("leaf.chlorophyll_sd", 0.f) > 0.f || cfg.f("leaf.chlorophyll_young_fraction", 1.f) < 1.f) {
        radiation.writePrimitiveDataLabelMap("camA", "leaf_N_map", base.str() + "_leafN", out);
    }
    if (cfg.i("output.write_leaf_ids", 0)) {
        if (leaf_objects_identified == 0) {
            helios_runtime_error("ERROR (render): output.write_leaf_ids is set but no leaf carries a leafObjectID, so the "
                                 "map would be written as zeros. This means getAllLeafUUIDs() returned nothing -- the scene "
                                 "has no leaves, or they were rebuilt after the IDs were assigned.");
        }
        radiation.writePrimitiveDataLabelMap("camA", "leafObjectID", base.str() + "_leafid", out);
    }
    // Per-pixel site index, the ray-traced counterpart of the label rasterizer's site map: the two
    // must agree pixel for pixel, which is how the rasterizer's axis convention is verified.
    if (cfg.i("output.write_site_ids", 0)) {
        radiation.writePrimitiveDataLabelMap("camA", "siteIndex", base.str() + "_site", out);
    }
    if (cfg.i("output.write_class_ids", 0)) {
        radiation.writePrimitiveDataLabelMap("camA", "organClass", base.str() + "_class", out);
    }
    radiation.writeCameraImage("camA", bands, base.str() + "_RGB", out);
    if (cfg.i("output.write_depth", 0)) {   // I/O addition (2026-09-28): per-pixel camera depth, metres, text map
        radiation.writeDepthImageData("camA", base.str() + "_depth", out);
    }
    // Both flower streams share class 0. The crop audit confirmed the real
    // annotations cover buds, open flowers and senescent flowers alike, so
    // splitting them here would create a class-definition gap that does not
    // exist in the target data.
    radiation.writeImageBoundingBoxes_ObjectData("camA", {"openflowerID", "closedflowerID"}, {0u, 0u},
                                                 base.str() + "_bbox", "classes.txt", out);
    std::cout << "wrote " << out << base.str() << "_RGB" << std::endl;
    return 0;
}


// --render-xml <plant.xml | list.txt> --camera <scene.json> --out <dir>   (I/O addition, 2026-09-28)
// Renders plant-structure XML files made elsewhere (refined reconstructions) through the unchanged render() path:
// the scene JSON names the base config and the key/value overrides of the twin render being matched (camera, lamp
// lighting, soil albedo map, leaf optics, rover), the plants replace the grown canopy through canopy.plant_xml, and
// the per-plant site map (siteIndex = list order + 1) is always written next to the RGB. Scene JSON:
//     {"config": "<baseline.cfg>", "seed": 1, "overrides": {"camera.hfov": 71.884, ...}}
int renderXML(int argc, char **argv) {
    std::string xml, camera, out;
    bool obj_mode = false;
    for (int i = 1; i + 1 < argc; i += 2) {
        const std::string k = argv[i];
        if (k == "--render-xml") xml = argv[i + 1];
        else if (k == "--render-obj") { xml = argv[i + 1]; obj_mode = true; }
        else if (k == "--camera") camera = argv[i + 1];
        else if (k == "--out") out = argv[i + 1];
        else throw std::runtime_error("unknown argument " + k);
    }
    if (xml.empty() || camera.empty() || out.empty()) {
        throw std::runtime_error("usage: --render-xml <plant.xml|list.txt> --camera <scene.json> --out <dir>");
    }
    std::ifstream jf(camera);
    if (!jf) throw std::runtime_error("cannot open scene json " + camera);
    const nlohmann::json j = nlohmann::json::parse(jf);
    Config cfg;
    cfg.load(j.at("config").get<std::string>());
    for (const auto &kv: j.at("overrides").items()) {
        const auto &v = kv.value();
        cfg.set(kv.key(), v.is_string() ? v.get<std::string>() : v.dump());
    }
    std::filesystem::create_directories(out);
    std::string list = xml;
    const std::string ext = xml.size() > 4 ? xml.substr(xml.size() - 4) : "";
    if (ext == ".xml" || ext == ".obj") {
        list = out + (obj_mode ? "/obj_list.txt" : "/plant_list.txt");
        std::ofstream(list) << xml << "\n";
    }
    if (obj_mode) {
        // --render-obj: meshes, not plants; the plant-only outputs are switched off (write_leaf_ids errors on a
        // scene without leaves), depth is written
        cfg.set("canopy.obj_list", list);
        cfg.set("output.write_leaf_ids", "0");
        cfg.set("output.write_depth", "1");
    } else {
        cfg.set("canopy.plant_xml", list);
    }
    cfg.set("output.folder", out + "/");
    cfg.set("output.write_site_ids", "1");
    return render(cfg, j.value("seed", 1u));
}
} // namespace

int main(int argc, char **argv) {
    const std::string mode = (argc > 1) ? argv[1] : "";
    try {
        if (mode == "--render-xml" || mode == "--render-obj" || mode == "--camera" || mode == "--out") {
            return renderXML(argc, argv);
        }
        if (mode == "prospect-grid") {
            return dumpProspectGrid(argc > 2 ? std::stoi(argv[2]) : 3000,
                                    argc > 3 ? std::stoul(argv[3]) : 1u,
                                    argc > 4 ? argv[4] : "../spectra/prospect_grid.txt");
        }
        if (mode == "raster") {
            Config cfg;
            cfg.load(argc > 2 ? argv[2] : "../config/baseline.cfg");
            for (int i = 4; i < argc; i += 2)          // key value overrides
                if (i + 1 < argc) cfg.set(argv[i], argv[i + 1]);
            return raster(cfg, argc > 3 ? std::stoul(argv[3]) : 1u);
        }
        if (mode == "geom") {
            Config cfg;
            cfg.load(argc > 2 ? argv[2] : "../config/baseline.cfg");
            for (int i = 4; i < argc; i += 2)          // key value overrides
                if (i + 1 < argc) cfg.set(argv[i], argv[i + 1]);
            return geom(cfg, argc > 3 ? std::stoul(argv[3]) : 1u);
        }
        if (mode == "render") {
            Config cfg;
            cfg.load(argc > 2 ? argv[2] : "../config/baseline.cfg");
            for (int i = 4; i < argc; i += 2)          // key value overrides
                if (i + 1 < argc) cfg.set(argv[i], argv[i + 1]);
            return render(cfg, argc > 3 ? std::stoul(argv[3]) : 1u);
        }
    } catch (const std::exception &e) {
        std::cerr << "ERROR: " << e.what() << std::endl;
        return 1;
    }
    std::cerr << "usage: " << argv[0] << " prospect-grid [n] [seed] [out]\n"
              << "       " << argv[0] << " render [config] [seed] [key value ...]\n"
              << "       " << argv[0] << " geom   [config] [seed] [key value ...]\n"
              << "       " << argv[0] << " raster [config] [seed] [key value ...]\n"
              << "       " << argv[0] << " --render-xml <plant.xml|list.txt> --camera <scene.json> --out <dir>\n"
              << "       " << argv[0] << " --render-obj <mesh.obj|obj_list.txt> --camera <scene.json> --out <dir>\n";
    return 1;
}
