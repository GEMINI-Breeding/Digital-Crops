"""Score a tiled synthetic set against the real set with the asymmetric objective."""
import glob, os, sys
import cv2, numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real.objective import score, render_table


def collect(d, n_images=40, seed=0):
    sizes, logasp, per_tile = [], [], []
    for f in sorted(glob.glob(os.path.join(d, "labels", "*.txt"))):
        n = 0
        for line in open(f):
            p = line.split()
            if len(p) >= 5:
                w, h = float(p[3]) * 640, float(p[4]) * 640
                if w > 0 and h > 0:
                    sizes.append(np.sqrt(w * h)); logasp.append(np.log(w / h)); n += 1
        per_tile.append(n)

    spacing = []
    for f in sorted(glob.glob(os.path.join(d, "labels", "*.txt"))):
        pts = [(float(p[1]) * 640, float(p[2]) * 640)
               for p in (l.split() for l in open(f)) if len(p) >= 5]
        if len(pts) < 2:
            continue
        P = np.array(pts)
        D = np.linalg.norm(P[:, None] - P[None], axis=-1)
        np.fill_diagonal(D, np.inf)
        spacing += D.min(1).tolist()

    imgs = sorted(glob.glob(os.path.join(d, "images", "*.jpg")) +
                  glob.glob(os.path.join(d, "images", "*.jpeg")))
    rng = np.random.default_rng(seed)
    imgs = [imgs[i] for i in rng.choice(len(imgs), min(n_images, len(imgs)), replace=False)]
    cover, chroma, lightness = [], [], []
    for f in imgs:
        bgr = cv2.imread(f)
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255
        s = rgb.sum(2) + 1e-6
        veg = 2 * rgb[:, :, 1] / s - rgb[:, :, 0] / s - rgb[:, :, 2] / s > 0.05
        cover.append(float(veg.mean()))
        lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
        a, b = lab[:, :, 1] - 128, lab[:, :, 2] - 128
        if veg.sum() > 100:
            chroma.append(float(np.median(np.sqrt(a[veg] ** 2 + b[veg] ** 2))))
            lightness.append(float(np.median(lab[:, :, 0][veg] * 100 / 255)))
    return dict(object_size_px=sizes, log_aspect=logasp, objects_per_tile=per_tile,
                nn_spacing_px=spacing, tile_cover=cover,
                foliage_chroma=chroma, foliage_lightness=lightness)


if __name__ == "__main__":
    real = collect("real")
    for target in sys.argv[1:] or ["synthetic_v17"]:
        rows, total = score(real, collect(target))
        print(f"\n=== {target} ===")
        print(render_table(rows, total))
