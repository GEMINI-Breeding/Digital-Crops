"""Develop raw radiance EXRs into dataset JPEGs, applying the camera chain in post.

Renders are made at manual exposure, so the EXR holds scene radiance with no gain. Exposure is
applied here instead, for two reasons.

Auto-exposure meters the whole frame, so the same leaf renders differently depending on how much
soil sits beside it: measured across the germination range, synthetic foliage swung 27 L* while the
real imagery swings under 4 across the same span of canopy cover. Metering also propagates errors --
this soil renders at L* 78 against a real 39.6, and auto-exposure was passing that error straight
into foliage brightness.

Applying a fixed gain here removes the coupling, and exposure variation can still be reintroduced
deliberately with --gain-jitter, which is the honest way round: if the real rig did auto-expose,
that shows up as spread in exposure, and spread is cheap to add and free under an objective that
never penalises being wider than real.
"""
import argparse, glob, json, os, sys
import cv2, numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real import camera_pipeline as cp


def foliage_lightness(rgb01, ground_mask=None):
    """Median L* of foliage. Uses the exact ground mask when one is available, since this soil is
    green enough that a colour test puts it in the foliage class."""
    bgr = np.clip(rgb01[:, :, ::-1] * 255, 0, 255).astype(np.uint8)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    L, a = lab[:, :, 0] * 100 / 255, lab[:, :, 1] - 128
    fol = (~ground_mask) if ground_mask is not None else (a < -5)
    return float(np.median(L[fol])) if fol.sum() > 500 else float("nan")


def load_ground(exr_path):
    stem = os.path.basename(exr_path).replace("_raw.exr", "")
    for cand in (os.path.join(os.path.dirname(exr_path), stem + "_ground.txt"),
                 os.path.join(os.path.dirname(exr_path), stem.replace("camA_", "") + "_ground.txt")):
        if os.path.exists(cand):
            g = np.loadtxt(cand)
            return np.isfinite(g) & (g > 0)
    return None


def calibrate_gain(exrs, target_L, cfg, lo=1.0, hi=1e6, iters=24):
    """Bisect for the single gain whose median foliage L* over the reference frames hits target_L."""
    def measure(gain):
        vals = []
        for f in exrs:
            out = cp.process(cp.read_raw_exr(f), exposure=gain, **cfg)
            vals.append(foliage_lightness(out, load_ground(f)))
        return float(np.nanmedian(vals))
    for _ in range(iters):
        mid = np.sqrt(lo * hi)
        if measure(mid) < target_L:
            lo = mid
        else:
            hi = mid
    return float(np.sqrt(lo * hi))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("frames")
    p.add_argument("--out", default=None, help="output folder (default: <frames>_dev)")
    p.add_argument("--gain", type=float, default=None,
                   help=f"fixed exposure gain; omit to calibrate. Dataset value: {cp.DEVELOP_GAIN}")
    p.add_argument("--target-L", type=float, default=47.84, help="real foliage median L*")
    p.add_argument("--gain-jitter", type=float, default=0.0, help="+/- fraction, applied per frame in log space")
    p.add_argument("--ccm", default=cp.DEVELOP_CCM)
    p.add_argument("--ccm-strength", type=float, default=1.0)
    p.add_argument("--knee", type=float, default=0.55)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()

    exrs = sorted(glob.glob(os.path.join(args.frames, "**", "*_raw.exr"), recursive=True))
    if not exrs:
        raise SystemExit(f"no *_raw.exr under {args.frames}")
    cfg = dict(ccm=args.ccm or None, ccm_strength=args.ccm_strength, highlight_knee=args.knee)

    gain = args.gain
    if gain is None:
        gain = calibrate_gain(exrs[: min(4, len(exrs))], args.target_L, cfg)
        print(f"calibrated gain {gain:.1f} for foliage L* {args.target_L}")

    out_dir = args.out or (args.frames.rstrip("/") + "_dev")
    os.makedirs(out_dir, exist_ok=True)
    rng = np.random.default_rng(args.seed)
    report = []
    for f in exrs:
        g = gain * float(np.exp(rng.uniform(-1, 1) * np.log1p(args.gain_jitter))) if args.gain_jitter > 0 else gain
        out = cp.process(cp.read_raw_exr(f), exposure=g, **cfg)
        name = os.path.basename(f).replace("_raw.exr", "_RGB.jpeg")
        cv2.imwrite(os.path.join(out_dir, name),
                    np.clip(out[:, :, ::-1] * 255, 0, 255).astype(np.uint8),
                    [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        L = foliage_lightness(out, load_ground(f))
        report.append(dict(frame=name, gain=g, foliage_L=L))
        print(f"  {name}  gain {g:8.1f}  foliage L* {L:5.1f}")
    json.dump(dict(gain=gain, jitter=args.gain_jitter, frames=report),
              open(os.path.join(out_dir, "develop.json"), "w"), indent=2)
    print(f"wrote {len(report)} frames to {out_dir}")


if __name__ == "__main__":
    main()
