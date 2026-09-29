"""Synthetic leaf length under the same selection the human applied to the real images.

The hand labels give the first direct measurement of real leaf length, but only for leaves whose
midrib the labeller could clearly see -- fully visible, roughly face-on, well lit. Comparing that
against a synthetic number drawn from all leaves would compare two different populations, so this
applies an objective analogue of the human's selection to the synthetic exact masks.

Two analogues are computed, because the strict one is not obviously the right reading of what a
person does. A human calls a leaf "fully visible" when they can see its outline and midrib; they do
not reject it because a stem crosses one lobe. The strict filter does reject exactly that, and in a
dense canopy large leaves are occluded more often than small ones, so the strict filter could bias
the synthetic distribution low in the same way SAM's extra masks bias the real one low.

  strict     one connected component, solidity >= 0.80, unclipped, face-on
  lenient    largest component holds >= 80% of the leaf's visible pixels, measured on that
             component's convex hull so a bite taken out of the middle does not shorten it,
             unclipped, face-on

Length is the fitted-ellipse major axis, the same quantity the hand line and the SAM ellipse measure.
No segmentation is involved on this side at all.
"""
import glob, json, os, subprocess, sys
import numpy as np, cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MIN_TRUTH_PX = 200
MIN_SOLIDITY = 0.80
ASPECT_MAX = 2.6
TILE_NATIVE, TILE = 1280, 640
N_TILES = 12
SEEDS = [9701, 9702]

BASE = json.load(open("audit/phase5_confirm.json"))["results"]["18"]["overrides"]
FID = json.load(open("audit/best_fidelity.json"))

CONFIGS = {
    "trial 18 (mAP winner)": dict(BASE),
    "best fidelity (S17)": {**BASE, **FID["arch"],
                            "canopy.germination_fraction_min": str(FID["germination"][0]),
                            "canopy.germination_fraction_max": str(FID["germination"][1])},
}


def render(ov, seed, raw):
    """Render one scene and return its per-pixel leaf identity map.

    No image is developed: this measurement is purely geometric, and the identity map is written
    straight out of the camera pixel-labelling pass. Trial 18's canopy peaks around 60 GB, so this
    script is meant to be submitted with its own memory allocation rather than run inside an
    interactive session (see scripts/truth_leaf_length.sbatch).
    """
    os.system(f"rm -rf {raw}")
    o = dict(ov); o["output.write_leaf_ids"] = "1"
    flat = [x for kv in o.items() for x in kv]
    r = subprocess.run(["./SyntheticAutotuning", "render", "../config/baseline.cfg", str(seed),
                        "camera.samples", "20", "output.folder", f"../{raw}/"] + flat,
                       capture_output=True, text=True, cwd="build-gpu")
    if r.returncode != 0:
        tail = "\n".join(r.stderr.strip().splitlines()[-3:])
        raise SystemExit(f"render rc={r.returncode}"
                         + (" (SIGKILL -- out of job memory)" if r.returncode == -9 else "")
                         + f"\n{tail}")
    ids = glob.glob(f"{raw}/camA_*_leafid.txt")
    if len(ids) != 1:
        raise SystemExit(f"expected one leaf id map in {raw}, found {len(ids)}")
    n = next((l for l in r.stdout.splitlines() if "DIAG leaf_object_ids" in l), "")
    print(f"  {n.strip()}", flush=True)
    return np.loadtxt(ids[0])


def lengths(idmap, rng):
    """Major axis of every whole, visible leaf in N_TILES dataset-style tiles."""
    H, W = idmap.shape
    out = {k: [] for k in ("every", "whole", "faceon", "lenient", "lenient_faceon")}
    for _ in range(N_TILES):
        x = int(rng.integers(0, W - TILE_NATIVE)); y = int(rng.integers(0, H - TILE_NATIVE))
        ids = cv2.resize(idmap[y:y+TILE_NATIVE, x:x+TILE_NATIVE], (TILE, TILE),
                         interpolation=cv2.INTER_NEAREST)
        for lid in np.unique(ids):
            if not np.isfinite(lid) or lid <= 0:
                continue
            m = (ids == lid)
            visible = int(m.sum())
            if visible < MIN_TRUTH_PX:
                continue
            cnt, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL,
                                      cv2.CHAIN_APPROX_SIMPLE)
            if not cnt:
                continue
            c = max(cnt, key=cv2.contourArea)
            if len(c) < 5:
                continue
            (_, (a1, a2), _) = cv2.fitEllipse(c)
            major, minor = max(a1, a2), min(a1, a2)
            if major <= TILE * 2 ** 0.5:          # a degenerate fit can return absurd axes
                out["every"].append(major)

            ys, xs = np.nonzero(m)
            if ys.min() == 0 or xs.min() == 0 or ys.max() == TILE-1 or xs.max() == TILE-1:
                continue                                    # clipped by the tile edge

            if len(cnt) == 1:
                hull = cv2.contourArea(cv2.convexHull(c))
                if hull > 0 and cv2.contourArea(c) / hull >= MIN_SOLIDITY:
                    out["whole"].append(major)
                    if minor > 0 and major / minor <= ASPECT_MAX:
                        out["faceon"].append(major)

            # Lenient: an occluder may cut into or across the leaf. Keep it if most of the visible
            # area is still one piece, and measure that piece's convex hull so a notch or a stem
            # lying across the blade does not shorten the axis.
            if cv2.contourArea(c) >= 0.80 * visible:
                h = cv2.convexHull(c)
                if len(h) >= 5:
                    (_, (b1, b2), _) = cv2.fitEllipse(h)
                    hmajor, hminor = max(b1, b2), min(b1, b2)
                    if hmajor <= TILE * 2 ** 0.5:
                        out["lenient"].append(hmajor)
                        if hminor > 0 and hmajor / hminor <= ASPECT_MAX:
                            out["lenient_faceon"].append(hmajor)
    return out


def pct(a, label):
    a = np.asarray(a, float)
    print(f"  {label:26s} n={a.size:5d}  p25 {np.percentile(a,25):6.1f}  p50 {np.median(a):6.1f}  "
          f"p75 {np.percentile(a,75):6.1f}  p90 {np.percentile(a,90):6.1f}")


if __name__ == "__main__":
    out = {}
    for name, ov in CONFIGS.items():
        acc = None
        for seed in SEEDS:
            idmap = render(ov, seed, "tll_raw")
            d = lengths(idmap, np.random.default_rng(seed))
            acc = d if acc is None else {k: acc[k] + d[k] for k in acc}
            print(f"{name}: seed {seed} done ({len(d['faceon'])} strict, "
                  f"{len(d['lenient_faceon'])} lenient)", flush=True)
        print(f"\n{name}")
        for k in ("every", "whole", "faceon", "lenient", "lenient_faceon"):
            pct(acc[k], k)
        out[name] = acc
    os.system("rm -rf tll_raw")

    hand = json.load(open("audit/handlabel_vs_sam.json"))["hand_whole"]
    print("\nREAL, hand-labelled fully-visible leaflets")
    pct(hand, "hand midrib length")
    A_REAL, A_SYN = 12 * 256 ** 2, TILE ** 2 * N_TILES * len(SEEDS)
    print("\nleaves longer than T, per megapixel:")
    for T in (80, 100, 120):
        line = f"  >{T:3d} px   real {(np.array(hand) > T).sum()/A_REAL*1e6:6.1f}"
        for name in CONFIGS:
            for k in ("faceon", "lenient_faceon"):
                line += f"   {name[:8]}/{k[:7]} {(np.array(out[name][k]) > T).sum()/A_SYN*1e6:6.1f}"
        print(line)
    json.dump(out, open("audit/truth_leaf_length.json", "w"))
    print("\nTRUTH LEAF LENGTH COMPLETE")
