"""The rate-split twin against the single-rate one, on the measures that motivated the change.

Blade-pixel radial density per plant against the photograph is the test the change was made on, so it is the test
it is judged by; cover and the mature organ sizes come along to show that filling the middle was not paid for by
breaking something that already matched. Maturity is taken by phytomer age, never by leaf_scale: a rate change
moves any leaf_scale threshold, which made the organ sizes appear to drift by 1.25x when nothing about a finished
organ had changed.

usage: twin_rate_compare.py [--frames FR,FR] [--suffixes _final,_rate]
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cv2  # noqa: E402
import numpy as np  # noqa: E402

import twin.fit as F  # noqa: E402
import twin.raster as TR  # noqa: E402
import twin.real as R  # noqa: E402

FRAMES = ["2023-06-20_Plot286-MAGIC083", "2023-06-20_Plot201-MAGIC262", "2023-06-27_Plot286-MAGIC083",
          "2023-06-27_Plot298-MAGIC226", "2023-07-03_Plot286-MAGIC083"]
MM, BINS = 0.783, 10

ap = argparse.ArgumentParser()
ap.add_argument("--frames", default=",".join(FRAMES))
ap.add_argument("--suffixes", default="_final,_rate")
ap.add_argument("--binary", default=None)
a = ap.parse_args()


def thin_fraction(mask, radius=3):
    """Share of foliage narrow enough to be a stalk: what does not survive an opening with a small disc.

    The radial profile says where a plant's area sits and not how much bare stalk shows, and the two can
    disagree -- the setting that best matched the profile hid the petioles almost entirely where the
    photograph shows some. Measurable on the photograph too, which a class map is not."""
    m = mask.astype(np.uint8)
    if not m.any():
        return float("nan")
    disc = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))
    return 1.0 - cv2.morphologyEx(m, cv2.MORPH_OPEN, disc).sum() / m.sum()


def radial(mask, cx, cy):
    ys, xs = np.nonzero(mask)
    if len(ys) < 50:
        return None
    r = np.hypot(xs - cx, ys - cy)
    r95 = np.percentile(r, 95)
    if r95 <= 0:
        return None
    counts, edges = np.histogram(r / r95, bins=BINS, range=(0, 1))
    density = counts / (np.pi * (edges[1:] ** 2 - edges[:-1] ** 2))
    return density / max(density.mean(), 1e-9)


for frame in a.frames.split(","):
    print(f"\n=== {frame} ===")
    real_profile = None
    for suffix in a.suffixes.split(","):
        work = os.path.join(TR.PROJECT, "twin_work", frame + suffix)
        fit = json.load(open(os.path.join(work, "fit.json")))
        ov = dict(fit["overrides"])
        ov["canopy.layout_file"] = os.path.join(work, "layout.txt")
        if real_profile is None:
            target = F.Target(fit["target"], work)
            target.plants(1500)
            _, _, labels = target.downsampled(F.px_scale(ov))
            real_profile = np.median(np.array([p for p in (radial(labels == s["label"], s["px"], s["py"])
                                                           for s in fit["sites"]) if p is not None]), axis=0)
            veg_real, _, _ = target.downsampled(F.px_scale(ov))
            real_thin = thin_fraction(veg_real & (labels > 0))
            print(f"{'real':22s} " + " ".join(f"{v:5.2f}" for v in real_profile) + f"   thin {real_thin:.3f}")
        height = float(ov["camera.height"])
        fx = 0.5 * R.WIDTH / np.tan(np.radians(0.5 * float(ov["camera.hfov"])))

        def project(p):
            p = np.atleast_2d(p)
            depth = height - p[:, 2]
            return np.stack([R.WIDTH / 2 + p[:, 0] * fx / depth, R.HEIGHT / 2 - p[:, 1] * fx / depth], 1)

        scratch = os.path.join(work, "ratecheck")
        ov.update({"diag.petiolecensus": 1, "diag.stalkdump": os.path.join(scratch, "stalks.txt"),
                   "diag.leafruler": os.path.join(scratch, "ruler.txt"), "raster.split_stems": 1})
        os.makedirs(scratch, exist_ok=True)
        out = TR.run(ov, seed=1, folder=scratch, base="rc", binary=a.binary or TR.BINARY, read_maps=False)
        maps = TR.Maps(scratch, "rc")
        site, cls = maps.full("site", 0), maps.full("class", 0)
        profile = np.median(np.array([p for p in (radial((site == k + 1) & (cls == 1), s["px"], s["py"])
                                                  for k, s in enumerate(fit["sites"])) if p is not None]), axis=0)
        cover = float(np.isin(cls, (1, 2, 3, 4, 5)).mean())
        thin = thin_fraction(np.isin(cls, (1, 2, 3, 4, 5, 7, 8)))

        d = np.loadtxt(os.path.join(scratch, "ruler.txt"), comments="#")
        blade = {int(o): (d[k, 3:6], d[k, 6:9]) for k, o in enumerate(d[:, 1])}
        stalk = {}
        for line in open(os.path.join(scratch, "stalks.txt")):
            if not line.startswith("#"):
                t = line.split()
                if t[0] == "petiole":
                    stalk[int(t[2])] = (np.array([float(x) for x in t[3:6]]), np.array([float(x) for x in t[6:9]]))
        lengths, petioles = [], []
        for line in out.splitlines():
            f = dict(re.findall(r"(\w+)=([-\d.e,]+)", line))
            if not line.startswith("PETIOLE") or int(f["leaflets"]) != 3 or float(f["age"]) < 12:
                continue
            objs = [int(x) for x in f["leaf_objs"].split(",")]
            blades = [float(np.linalg.norm(project(blade[o][1]) - project(blade[o][0])) * MM) for o in objs if o in blade]
            petiole_obj = int(f["petiole_obj"])
            if blades and petiole_obj in stalk:
                lengths.append(np.median(blades))
                petioles.append(float(np.linalg.norm(project(stalk[petiole_obj][1]) - project(stalk[petiole_obj][0])) * MM))
        print(f"{suffix:22s} " + " ".join(f"{v:5.2f}" for v in profile) +
              f"   L1 {np.abs(profile - real_profile).sum():5.2f}   thin {thin:.3f} ({thin / max(real_thin, 1e-9) - 1:+.0%})   cover {cover:.3f}"
              f"   mature blade {np.median(lengths):4.1f} petiole {np.median(petioles):4.1f} mm (n={len(lengths)})")
