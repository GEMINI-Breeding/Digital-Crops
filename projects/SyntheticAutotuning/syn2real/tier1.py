"""Run Tier-1 feature-space metrics and write a summary."""
import json
import numpy as np
from .io import Dataset
from . import features as F


def run(real_root='real', syn_root='synthetic', outdir='audit'):
    m, tf, dev = F.get_model()
    R, S = Dataset(real_root), Dataset(syn_root)

    Xr = F.embed_dataset(R, m, tf, dev)
    Xs = F.embed_dataset(S, m, tf, dev)
    print(f'embeddings: real {Xr.shape}  synthetic {Xs.shape}')

    # Real-vs-real baseline: the irreducible floor from finite sampling.
    # Without it, an absolute KID number means nothing.
    rng = np.random.default_rng(0)
    idx = rng.permutation(len(Xr)); h = len(Xr) // 2
    kid_rr = F.kid(Xr[idx[:h]], Xr[idx[h:]], subset_size=min(100, h))
    kid_rs = F.kid(Xr, Xs)
    out = {
        'kid_real_vs_real_baseline': kid_rr,
        'kid_real_vs_synthetic': kid_rs,
        'prdc_scene': F.prdc(Xr, Xs, k=5),
        'domain_auc_scene': F.domain_auc(Xr, Xs),
    }

    Cr = F.object_crops(R, m, tf, dev)
    Cs = F.object_crops(S, m, tf, dev)
    print(f'object crops: real {Cr.shape}  synthetic {Cs.shape}')
    ci = rng.permutation(len(Cr)); ch = len(Cr) // 2
    out['ccdm_real_vs_real_baseline'] = F.ccdm(Cr[ci[:ch]], Cr[ci[ch:]], subset_size=min(100, ch))
    out['ccdm_real_vs_synthetic'] = F.ccdm(Cr, Cs)
    out['prdc_object'] = F.prdc(Cr[:1500], Cs[:1500], k=5)
    out['domain_auc_object'] = F.domain_auc(Cr, Cs)

    json.dump(out, open(f'{outdir}/tier1.json', 'w'), indent=2)
    return out


if __name__ == '__main__':
    o = run()
    print()
    print('=== Tier-1 feature-space metrics (DINOv2 ViT-B/14) ===')
    print(f"KID scene   real-vs-real  {o['kid_real_vs_real_baseline'][0]:+.4f} +- {o['kid_real_vs_real_baseline'][1]:.4f}   <- noise floor")
    print(f"KID scene   real-vs-syn   {o['kid_real_vs_synthetic'][0]:+.4f} +- {o['kid_real_vs_synthetic'][1]:.4f}")
    print(f"CCDM crops  real-vs-real  {o['ccdm_real_vs_real_baseline'][0]:+.4f} +- {o['ccdm_real_vs_real_baseline'][1]:.4f}   <- noise floor")
    print(f"CCDM crops  real-vs-syn   {o['ccdm_real_vs_synthetic'][0]:+.4f} +- {o['ccdm_real_vs_synthetic'][1]:.4f}")
    print()
    for k in ('prdc_scene', 'prdc_object'):
        p = o[k]
        print(f"{k:13} precision={p['precision']:.3f} recall={p['recall']:.3f} "
              f"density={p['density']:.3f} COVERAGE={p['coverage']:.3f}")
    print()
    print(f"domain AUC (scene)  {o['domain_auc_scene']:.4f}   (0.5 = indistinguishable)")
    print(f"domain AUC (object) {o['domain_auc_object']:.4f}")
