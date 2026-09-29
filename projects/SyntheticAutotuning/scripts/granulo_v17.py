"""Pattern spectra at leaf scale, written to JSON for the report figures.

Uses a downsampled image and correspondingly halved radii: a 243 px morphological kernel on a
640 px tile costs more than the resolution justifies, and the spectrum is scale-covariant, so
working at half size and doubling the reported radii gives the same curve for a quarter the cost.
"""
import glob, json, os, sys
import cv2, numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real.geometry import granulometry

HALF_RADII = list(range(1, 61, 3))            # in half-resolution pixels
RADII = [2 * r for r in HALF_RADII]           # reported in tile pixels
N = 40

def spectrum(d, seed=0):
    fs = sorted(glob.glob(os.path.join(d, "images", "*.jpg")) +
                glob.glob(os.path.join(d, "images", "*.jpeg")))
    rng = np.random.default_rng(seed)
    fs = [fs[i] for i in rng.choice(len(fs), min(N, len(fs)), replace=False)]
    acc = np.zeros(len(HALF_RADII))
    for f in fs:
        g = cv2.cvtColor(cv2.imread(f), cv2.COLOR_BGR2GRAY)
        g = cv2.resize(g, (g.shape[1] // 2, g.shape[0] // 2), interpolation=cv2.INTER_AREA)
        acc += granulometry(g, HALF_RADII)
    return acc / len(fs), len(fs)

out = {"radii": RADII}
for name, d in [("real", "real"), ("v17", "synthetic_v17"),
                ("prev", "synthetic_final"), ("base", "synthetic")]:
    s, n = spectrum(d)
    mean_r = float((s * np.array(RADII)).sum() / s.sum())
    out[name] = {"spec": s.tolist(), "n": n, "peak_r": RADII[int(np.argmax(s))], "mean_r": mean_r}
    print(f"{name:6s} n={n:3d} peak_r={out[name]['peak_r']:3d}px mean_r={mean_r:5.1f}px", flush=True)
json.dump(out, open("audit/granulo_v17.json", "w"))
print("GRANULO COMPLETE", flush=True)
