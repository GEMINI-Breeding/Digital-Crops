"""Leaf appearance against the whole foliage colour distribution of a real frame, one render per candidate.

The earlier per-frame chlorophyll matched the median foliage a*/b* only. The rendered foliage then had the right median but
none of the real frame's bright, saturated yellow-green tail. This scores a candidate by the foliage percentiles L* p10/p90,
a* and b* p10/p50/p90 and C* p90 (L* p50 is matched by the exposure gain), as the RMS difference from the real frame.

Each candidate is a dict of leaf keys (leaf.chlorophyll, leaf.chlorophyll_sd, leaf.Car_to_Cab_ratio, leaf.specular_scale, ...)
written as the render's leaf_overrides.txt over the twin's geometry overrides.
usage: twin_leaf_colour_fit.py <frame> <workdir_suffix> <geometry_overrides.json> '<json list of candidate dicts>' [--tag name]
Writes twin_work/colour/<frame>/<tag>_<k>/ renders and twin_work/colour/<frame>/<tag>.json.
"""
import argparse
import glob
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cv2  # noqa: E402
import numpy as np  # noqa: E402

import twin.appearance as A  # noqa: E402
import twin.fit as F  # noqa: E402
import twin.raster as TR  # noqa: E402

WB = (1.563, 1.0, 1.596)
METRICS = ["L10", "L90", "a10", "a50", "a90", "b10", "b50", "b90", "C90"]
ccm = A.CP.read_ccm(os.path.join(TR.PROJECT, "calib", "ccm_camA_20230728.xml"))


def lab(rgb):
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32) * np.array([100 / 255, 1, 1]) - np.array([0, 128, 128])


def percentiles(rgb, mask):
    L = lab(rgb)[mask]
    C = np.hypot(L[:, 1], L[:, 2])
    p = lambda x, q: float(np.percentile(x, q))
    return dict(L10=p(L[:, 0], 10), L50=p(L[:, 0], 50), L90=p(L[:, 0], 90), a10=p(L[:, 1], 10), a50=p(L[:, 1], 50), a90=p(L[:, 1], 90),
                b10=p(L[:, 2], 10), b50=p(L[:, 2], 50), b90=p(L[:, 2], 90), C50=p(C, 50), C90=p(C, 90))


def distance(syn, real):
    return float(np.sqrt(np.mean([(syn[m] - real[m]) ** 2 for m in METRICS])))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frame")
    ap.add_argument("suffix")
    ap.add_argument("geometry")
    ap.add_argument("candidates")
    ap.add_argument("--tag", default="grid")
    a = ap.parse_args()
    src = os.path.join(TR.PROJECT, "twin_work", a.frame + a.suffix)
    fit_dir = os.path.join(TR.PROJECT, "twin_work", a.frame + a.suffix.replace("_obj", ""))
    t = F.Target(json.load(open(os.path.join(fit_dir, "fit.json")))["target"], fit_dir)
    real = percentiles(t.rgb, t.veg)
    out_root = os.path.join(TR.PROJECT, "twin_work", "colour", a.frame)
    os.makedirs(out_root, exist_ok=True)
    results = dict(frame=a.frame, real=real, candidates=[])
    print(f"real   " + "  ".join(f"{m} {real[m]:5.1f}" for m in METRICS), flush=True)
    for k, cand in enumerate(json.loads(a.candidates)):
        wd = os.path.join(out_root, f"{a.tag}_{k}")
        os.makedirs(wd, exist_ok=True)
        for f in ("layout.txt", "soil_albedo.bin"):
            subprocess.run(["cp", os.path.join(src, f), wd], check=True)
        leaf = {"leaf.nitrogen_model": 0}
        leaf.update(cand)
        open(os.path.join(wd, "leaf_overrides.txt"), "w").write(" ".join(f"{key} {value}" for key, value in leaf.items()))
        r = subprocess.run(["bash", os.path.join(TR.PROJECT, "scripts", "twin_render_many.sh"), os.path.abspath(a.geometry), wd], capture_output=True, text=True)
        exrs = glob.glob(os.path.join(wd, "render_soil", "*_raw.exr"))
        if r.returncode != 0 or not exrs:
            raise RuntimeError(f"render failed for candidate {k} ({cand}):\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
        raw = A.read_exr(exrs[0])
        site = A.label_map(glob.glob(os.path.join(wd, "render_soil", "*_site.txt"))[0])
        gain = A.fit_gain(raw, real["L50"], site > 0, wb=WB, ccm=ccm)
        syn = percentiles(A.develop(raw, gain, wb=WB, ccm=ccm), site > 0)
        d = distance(syn, real)
        results["candidates"].append(dict(k=k, settings=cand, percentiles=syn, distance=d, gain=gain, workdir=wd))
        print(f"{k:2d} d {d:4.1f} " + "  ".join(f"{m} {syn[m]:5.1f}" for m in METRICS) + f"   {cand}", flush=True)
        json.dump(results, open(os.path.join(out_root, f"{a.tag}.json"), "w"), indent=1)
    best = min(results["candidates"], key=lambda c: c["distance"])
    print(f"best: {best['k']} d {best['distance']:.2f} {best['settings']}")


if __name__ == "__main__":
    main()
