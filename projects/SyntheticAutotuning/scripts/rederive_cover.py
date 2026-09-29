"""Re-derive cover and colour statistics from exact ground masks rather than pixel classification.

Both sets of numbers previously in the report were computed over pixels selected by Excess Green or
a CIELAB a* threshold. On the synthetic side this soil renders green (a* -5.9 against a real soil's
+2.4), so those masks put soil in the foliage class: cover was overstated -- 0.98 by ExG on a frame
whose true canopy is 0.30 -- and every "foliage" colour statistic was an average of leaves and soil.

The renderer writes an exact ground mask, so on the synthetic side nothing has to be inferred. The
real side has no ground truth and still needs a classifier; what changes is that the classifier can
now be checked against exact masks on synthetic before being trusted on real.
"""
import glob, os, sys
import cv2, numpy as np


def lab_of(bgr):
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    return lab[:, :, 0] * 100 / 255, lab[:, :, 1] - 128, lab[:, :, 2] - 128


def exg_of(bgr):
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255
    s = rgb.sum(2) + 1e-6
    return 2 * rgb[:, :, 1] / s - rgb[:, :, 0] / s - rgb[:, :, 2] / s


def synthetic_frame(d):
    """Exact statistics for one rendered frame with its ground and rover masks."""
    img = sorted(glob.glob(os.path.join(d, "*RGB.jpeg")))
    gnd = sorted(glob.glob(os.path.join(d, "*_ground.txt")))
    rov = sorted(glob.glob(os.path.join(d, "*_rover.txt")))
    if not (img and gnd):
        return None
    bgr = cv2.imread(img[0])
    gm = np.loadtxt(gnd[0])
    ground = np.isfinite(gm) & (gm > 0)
    rover = np.zeros_like(ground)
    if rov:
        rv = np.loadtxt(rov[0])
        rover = np.isfinite(rv) & (rv > 0)
    scene = ~rover                       # the rover is hardware, not part of the plot
    foliage = scene & ~ground
    L, a, b = lab_of(bgr)
    exg = exg_of(bgr)
    return dict(
        cover_exact=float(foliage.sum() / scene.sum()),
        cover_exg=float(np.mean(exg > 0.05)),
        cover_a=float(np.mean(a < -5)),
        fol_L=float(np.median(L[foliage])), fol_a=float(np.median(a[foliage])),
        fol_C=float(np.median(np.sqrt(a[foliage] ** 2 + b[foliage] ** 2))),
        soil_L=float(np.median(L[ground & scene])), soil_a=float(np.median(a[ground & scene])),
        soil_b=float(np.median(b[ground & scene])),
    )


def real_stats(d="real", n=40, seed=0):
    """Real tiles, classified by a* since there is no ground truth. Soil is a*>0, foliage a*<-5."""
    fs = sorted(glob.glob(os.path.join(d, "images", "*.jpg")))
    rng = np.random.default_rng(seed)
    fs = [fs[i] for i in rng.choice(len(fs), min(n, len(fs)), replace=False)]
    cov, fL, fa, fC, sL, sa, sb = ([] for _ in range(7))
    for f in fs:
        bgr = cv2.imread(f)
        L, a, b = lab_of(bgr)
        fol, soil = a < -5, a > 0
        cov.append(float(fol.mean()))
        if fol.sum() > 500:
            fL.append(np.median(L[fol])); fa.append(np.median(a[fol]))
            fC.append(np.median(np.sqrt(a[fol] ** 2 + b[fol] ** 2)))
        if soil.sum() > 500:
            sL.append(np.median(L[soil])); sa.append(np.median(a[soil])); sb.append(np.median(b[soil]))
    m = lambda v: float(np.median(v)) if v else float("nan")
    return dict(cover=m(cov), cover_p5=float(np.percentile(cov, 5)), cover_p95=float(np.percentile(cov, 95)),
                fol_L=m(fL), fol_a=m(fa), fol_C=m(fC), soil_L=m(sL), soil_a=m(sa), soil_b=m(sb),
                n_soil_tiles=len(sL), n=len(fs))


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "frames_ground"
    print(f"{'frame':>10s} {'EXACT':>7s} {'a*<-5':>7s} {'ExG':>7s} | {'fol L*':>7s} {'fol a*':>7s} {'fol C*':>7s} | {'soil L*':>8s} {'soil a*':>8s} {'soil b*':>8s}")
    print("-" * 96)
    for d in sorted(glob.glob(os.path.join(root, "g*"))):
        r = synthetic_frame(d)
        if r is None:
            continue
        print(f"{os.path.basename(d):>10s} {r['cover_exact']:7.3f} {r['cover_a']:7.3f} {r['cover_exg']:7.3f} | "
              f"{r['fol_L']:7.1f} {r['fol_a']:7.1f} {r['fol_C']:7.1f} | {r['soil_L']:8.1f} {r['soil_a']:8.1f} {r['soil_b']:8.1f}")
    R = real_stats()
    print("-" * 96)
    print(f"{'REAL':>10s} {R['cover']:7.3f} {'(a*)':>7s} {'':7s} | {R['fol_L']:7.1f} {R['fol_a']:7.1f} {R['fol_C']:7.1f} | "
          f"{R['soil_L']:8.1f} {R['soil_a']:8.1f} {R['soil_b']:8.1f}")
    print(f"{'':10s} real cover p5-p95 {R['cover_p5']:.3f}-{R['cover_p95']:.3f}; "
          f"soil measured on {R['n_soil_tiles']} of {R['n']} tiles that contain a*>0 pixels")
