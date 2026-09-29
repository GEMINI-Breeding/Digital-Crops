"""Attribution experiment: how much of the domain gap is cheap post-processing?

Applies a chain of post-hoc corrections to the SYNTHETIC images and re-measures
the feature-space gap after each. Corrections that can be applied in post
(JPEG, noise, sharpness, global colour) are things Phase 2 can fix in the
render/export pipeline. Whatever gap SURVIVES all of them is genuine
scene/geometry/material mismatch that only Phases 3-5 can close.
"""
import numpy as np
import cv2
from PIL import Image

from .io import Dataset
from . import features as F
from .stats_image import image_stats, _noise_sigma


def jpeg_quality_for_quant_sum(target, lo=30, hi=100):
    """Find the libjpeg quality whose luma quant table sums closest to target."""
    import struct
    probe = (np.random.default_rng(0).random((64, 64, 3)) * 255).astype(np.uint8)

    def qsum(q):
        ok, buf = cv2.imencode('.jpg', probe, [int(cv2.IMWRITE_JPEG_QUALITY), q])
        d = buf.tobytes()
        i = 2
        while i < len(d) - 1:
            if d[i] != 0xFF:
                break
            m = d[i + 1]
            if m in (0xD8, 0xD9):
                i += 2; continue
            if m == 0xDA:
                break
            ln = struct.unpack('>H', d[i + 2:i + 4])[0]
            if m == 0xDB:
                return int(sum(d[i + 5:i + 69]))
            i += 2 + ln
        return None
    best = min(range(lo, hi + 1), key=lambda q: abs((qsum(q) or 10 ** 9) - target))
    return best, qsum(best)


def apply_jpeg(rgb, q):
    ok, buf = cv2.imencode('.jpg', cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
                           [int(cv2.IMWRITE_JPEG_QUALITY), int(q)])
    return cv2.cvtColor(cv2.imdecode(buf, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)


def apply_noise(rgb, sigma, rng):
    out = rgb.astype(np.float32) + rng.normal(0, sigma, rgb.shape).astype(np.float32)
    return np.clip(out, 0, 255).astype(np.uint8)


def apply_unsharp(rgb, amount):
    blur = cv2.GaussianBlur(rgb.astype(np.float32), (0, 0), 1.2)
    out = rgb.astype(np.float32) * (1 + amount) - blur * amount
    return np.clip(out, 0, 255).astype(np.uint8)


def apply_color_match(rgb, src_stats, dst_stats):
    """Reinhard transfer in Lab: shift/scale synthetic Lab to the real mean/std.

    A DIAGNOSTIC only -- the real fix belongs in the renderer's spectra,
    exposure and white balance. This just measures how much of the gap colour
    alone accounts for.
    """
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    for c in range(3):
        sm, ss = src_stats[c]
        dm, dsd = dst_stats[c]
        lab[..., c] = (lab[..., c] - sm) * (dsd / max(ss, 1e-3)) + dm
    return cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)


def lab_moments(ds, limit=None):
    stems = ds.stems if limit is None else ds.stems[:limit]
    acc = np.zeros((3, 2))
    for s in stems:
        lab = cv2.cvtColor(ds.read_rgb(s), cv2.COLOR_RGB2LAB).astype(np.float32)
        for c in range(3):
            acc[c] += (lab[..., c].mean(), lab[..., c].std())
    return acc / len(stems)


def run(real_root='real', syn_root='synthetic', n_syn=500, outdir='audit'):
    R, S = Dataset(real_root), Dataset(syn_root)
    rng = np.random.default_rng(0)
    m, tf, dev = F.get_model()

    Xr = F.embed_dataset(R, m, tf, dev)

    # targets measured from the real set
    q, qs = jpeg_quality_for_quant_sum(1858)
    real_sig = np.median([_noise_sigma(cv2.cvtColor(R.read_rgb(s), cv2.COLOR_RGB2GRAY))
                          for s in R.stems[:80]])
    syn_sig = np.median([_noise_sigma(cv2.cvtColor(S.read_rgb(s), cv2.COLOR_RGB2GRAY))
                         for s in S.stems[:80]])
    add_sig = float(np.sqrt(max(real_sig ** 2 - syn_sig ** 2, 0.0)))
    mom_r, mom_s = lab_moments(R), lab_moments(S, 300)
    print(f'JPEG quality {q} (quant sum {qs} vs real 1858); noise to add sigma={add_sig:.2f}; '
          f'real noise {real_sig:.2f} syn {syn_sig:.2f}')

    stems = list(S.stems); rng.shuffle(stems); stems = stems[:n_syn]
    base = [S.read_rgb(s) for s in stems]

    chains = {
        'baseline':            lambda a: a,
        '+jpeg':               lambda a: apply_jpeg(a, q),
        '+jpeg+sharpen':       lambda a: apply_jpeg(apply_unsharp(a, 0.6), q),
        '+jpeg+sharpen+noise': lambda a: apply_jpeg(apply_noise(apply_unsharp(a, 0.6), add_sig, rng), q),
        '+all+colour':         lambda a: apply_jpeg(
                                    apply_noise(
                                        apply_unsharp(apply_color_match(a, mom_s, mom_r), 0.6),
                                        add_sig, rng), q),
    }

    rows = []
    for name, fn in chains.items():
        ims = [Image.fromarray(fn(a)) for a in base]
        X = F.embed_images(ims, m, tf, dev)
        auc = F.domain_auc(Xr, X)
        k, ke = F.kid(Xr, X)
        p = F.prdc(Xr, X, k=5)
        rows.append(dict(chain=name, domain_auc=auc, kid=k, kid_se=ke,
                         coverage=p['coverage'], precision=p['precision']))
        print(f"{name:22} AUC={auc:.4f}  KID={k:8.3f}  coverage={p['coverage']:.3f}")

    import pandas as pd
    df = pd.DataFrame(rows)
    df.to_csv(f'{outdir}/ablation_postproc.csv', index=False)
    return df


if __name__ == '__main__':
    print(run().to_string(index=False))
