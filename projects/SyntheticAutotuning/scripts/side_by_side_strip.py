"""One figure: real, the shipped training set, and the corrected architecture, at matched cover.

Section 08's strip is still trial 18 and section 18's is synthetic-only, so the report has never
shown the corrected architecture beside real imagery. Section 19 measured the leaf-size gap directly
and found it larger than SAM had said, which makes a like-for-like picture worth having.

Every panel carries a 100 mm scale bar. The ground sample distance is 0.880 mm per tile pixel in
both domains -- verified against the colour board to 3 percent in section 17 -- so the bars are
directly comparable and the comparison does not rest on the reader's sense of scale.
"""
import glob, os, subprocess, sys
import numpy as np, cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
from syn2real import camera_pipeline as cp
from syn2real.tile import tile_frame

MM_PER_PX = 0.880
PANEL = 320
BASE = json.load(open("audit/phase5_confirm.json"))["results"]["18"]["overrides"]
FID = json.load(open("audit/best_fidelity.json"))
SEEDS = range(10500, 10504)

CONFIGS = [
    ("trial 18 - the shipped training set", dict(BASE), "t18"),
    ("section 18 corrected architecture", {**BASE, **FID["arch"],
        "canopy.germination_fraction_min": str(FID["germination"][0]),
        "canopy.germination_fraction_max": str(FID["germination"][1])}, "arch"),
]


def build(ov, tag):
    raw, dev, tiles = f"sbs_raw_{tag}", f"sbs_dev_{tag}", f"sbs_tiles_{tag}"
    for d in (raw, dev, tiles):
        os.system(f"rm -rf {d}")
    flat = [x for kv in ov.items() for x in kv]
    for seed in SEEDS:
        r = subprocess.run(["./SyntheticAutotuning", "render", "../config/baseline.cfg", str(seed),
                            "camera.samples", "50", "output.folder", f"../{raw}/"] + flat,
                           capture_output=True, text=True, cwd="build-gpu")
        if r.returncode != 0:
            tail = "\n".join(r.stderr.strip().splitlines()[-3:])
            raise SystemExit(f"render rc={r.returncode}"
                             + (" (SIGKILL -- out of job memory)" if r.returncode == -9 else "")
                             + f"\n{tail}")
    subprocess.run(["env/bin/python", "scripts/develop.py", raw, "--out", dev,
                    "--target-L", str(cp.REAL_FOLIAGE_L)], check=True, capture_output=True)
    written = []
    for i, img in enumerate(sorted(glob.glob(os.path.join(dev, "*_RGB.jpeg")))):
        stem = os.path.basename(img).replace("camA_", "").replace("_RGB.jpeg", "")
        lbl = os.path.join(raw, stem + "_bbox.txt")
        if not os.path.exists(lbl):
            continue
        written += tile_frame(img, lbl, tiles, n_tiles=15, seed=8300 + i,
                              rover_mask_path=os.path.join(raw, "camA_" + stem + "_rover.txt"),
                              ground_mask_path=os.path.join(raw, "camA_" + stem + "_ground.txt"))
    order = sorted((t[1], t[0]) for t in written)
    out = []
    for q in (0.25, 0.50, 0.75):
        cover, name = order[int(q * (len(order) - 1))]
        out.append((cover, glob.glob(os.path.join(tiles, "images", name + ".*"))[0]))
    print(f"  {tag}: {len(written)} tiles, cover p25/p50/p75 "
          + "/".join(f"{c:.3f}" for c, _ in out), flush=True)
    return out, raw, dev, tiles


def real_panels():
    """Real tiles at the same three cover percentiles of their own set (a* < -5, no ground truth)."""
    fs = sorted(glob.glob("real/images/*.jpg"))
    cov = []
    for f in fs:
        lab = cv2.cvtColor(cv2.imread(f), cv2.COLOR_BGR2LAB)
        cov.append((float(((lab[:, :, 1].astype(np.float32) - 128) < -5).mean()), f))
    cov.sort()
    out = [cov[int(q * (len(cov) - 1))] for q in (0.25, 0.50, 0.75)]
    print(f"  real: {len(cov)} tiles, cover p25/p50/p75 "
          + "/".join(f"{c:.3f}" for c, _ in out), flush=True)
    return out


def panel(path, cover):
    img = cv2.resize(cv2.imread(path), (PANEL, PANEL), interpolation=cv2.INTER_AREA)
    scale_px = 100.0 / MM_PER_PX * PANEL / 640          # 100 mm in this panel's pixels
    x0, y = 14, PANEL - 18
    cv2.line(img, (x0, y), (int(x0 + scale_px), y), (0, 0, 0), 5, cv2.LINE_AA)
    cv2.line(img, (x0, y), (int(x0 + scale_px), y), (255, 255, 255), 3, cv2.LINE_AA)
    for c, t in (((0, 0, 0), 3), ((255, 255, 255), 1)):
        cv2.putText(img, "100 mm", (x0, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, c, t, cv2.LINE_AA)
        cv2.putText(img, f"cover {cover:.2f}", (x0, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.45, c, t,
                    cv2.LINE_AA)
    return img


if __name__ == "__main__":
    rows, scratch = [("real imagery", real_panels())], []
    for label, ov, tag in CONFIGS:
        sel, *dirs = build(ov, tag)
        rows.append((label, sel))
        scratch += dirs
    gap = np.full((PANEL, 8, 3), 30, np.uint8)
    strips = []
    for label, sel in rows:
        strip = panel(*sel[0][::-1])
        for cover, path in sel[1:]:
            strip = np.hstack([strip, gap, panel(path, cover)])
        strips.append(strip)
    hgap = np.full((10, strips[0].shape[1], 3), 30, np.uint8)
    fig = strips[0]
    for s in strips[1:]:
        fig = np.vstack([fig, hgap, s])
    cv2.imwrite("audit/side_by_side.jpg", fig, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    print(f"\nwrote audit/side_by_side.jpg {fig.shape}  rows: "
          + " | ".join(l for l, _ in rows))
    for d in scratch:
        os.system(f"rm -rf {d}")
    print("SIDE BY SIDE COMPLETE")
