"""Phase-1 deliverable: ranked gap report + paired distribution figures."""
import os
import numpy as np
import pandas as pd

from .io import Dataset
from . import stats_label, stats_image
from .compare import compare_all


def build(real_root='real', syn_root='synthetic', outdir='audit', limit=None):
    R, S = Dataset(real_root), Dataset(syn_root)
    print(f'real={len(R)} images  synthetic={len(S)} images')

    rs, ss = stats_label.all_stats(R), stats_label.all_stats(S)
    print('label statistics done')
    rs.update(stats_image.collect(R, limit)); print('real image statistics done')
    ss.update(stats_image.collect(S, limit)); print('synthetic image statistics done')

    df = compare_all(rs, ss)
    os.makedirs(outdir, exist_ok=True)
    df.to_csv(f'{outdir}/gap_report.csv')
    _figures(rs, ss, df, outdir)
    return df, rs, ss


def _figures(rs, ss, df, outdir):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    keys = list(df.index)
    n = len(keys)
    cols = 5
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(3.1 * cols, 2.3 * rows))
    for ax, k in zip(np.ravel(axes), keys):
        r = np.asarray(rs[k], float); r = r[np.isfinite(r)]
        s = np.asarray(ss[k], float); s = s[np.isfinite(s)]
        lo = min(np.percentile(r, 1), np.percentile(s, 1))
        hi = max(np.percentile(r, 99), np.percentile(s, 99))
        if not np.isfinite(lo) or not np.isfinite(hi) or hi - lo < 1e-12:
            lo, hi = lo - 1, hi + 1
        bins = np.linspace(lo, hi, 45)
        ax.hist(r, bins=bins, density=True, alpha=.55, color='#2b7bba', label='real')
        ax.hist(s, bins=bins, density=True, alpha=.55, color='#d1495b', label='syn')
        ax.set_title(f"{k}  [{df.loc[k,'verdict']}]\n"
                     f"W1={df.loc[k,'w1_norm']:.2f}  covdef={df.loc[k,'cov_deficit']:.2f}", fontsize=7)
        ax.tick_params(labelsize=6); ax.set_yticks([])
    for ax in np.ravel(axes)[n:]:
        ax.axis('off')
    np.ravel(axes)[0].legend(fontsize=6)
    fig.tight_layout()
    fig.savefig(f'{outdir}/gap_distributions.png', dpi=115)
    plt.close(fig)


def render_markdown(df, path):
    lines = ['| statistic | verdict | real med | syn med | W1/IQR | shift/IQR | cov deficit | controlled by |',
             '|---|---|---:|---:|---:|---:|---:|---|']
    for k, r in df.iterrows():
        w1 = '--' if r.both_constant else f'**{r.w1_norm:.2f}**'
        sh = '--' if r.both_constant else f'{r.shift_norm:+.2f}'
        lines.append(f"| `{k}` | {r.verdict} | {r.real_median:.3g} | {r.syn_median:.3g} | "
                     f"{w1} | {sh} | {r.cov_deficit:.2f} | {r.controls} |")
    open(path, 'w').write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    df, rs, ss = build()
    render_markdown(df, 'audit/gap_report.md')
    pd.set_option('display.width', 200)
    print(df[['real_median', 'syn_median', 'w1_norm', 'shift_norm', 'cov_deficit']].to_string())
