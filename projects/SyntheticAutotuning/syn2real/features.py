"""Tier-1 feature-space gap metrics on DINOv2 embeddings.

DINOv2 rather than Inception-v3: a closed cowpea canopy is far outside
ImageNet's mode, which is exactly the regime where Inception features are
documented to be uninformative.

KID rather than FID: with only 263 real tiles we are far below the feature
dimension, where the Frechet estimator is badly biased. KID's MMD estimator
is unbiased at small sample size.
"""
import numpy as np
import torch


def get_model(name='vit_base_patch14_dinov2.lvd142m', device='cuda'):
    import timm
    m = timm.create_model(name, pretrained=True, num_classes=0).eval().to(device)
    cfg = timm.data.resolve_data_config({}, model=m)
    tf = timm.data.create_transform(**cfg, is_training=False)
    return m, tf, device


@torch.no_grad()
def embed_images(pil_images, model, tf, device, batch=32):
    out = []
    for i in range(0, len(pil_images), batch):
        x = torch.stack([tf(im) for im in pil_images[i:i + batch]]).to(device)
        out.append(model(x).float().cpu().numpy())
    return np.concatenate(out)


@torch.no_grad()
def embed_dataset(ds, model, tf, device, limit=None, batch=32):
    from PIL import Image
    stems = ds.stems if limit is None else ds.stems[:limit]
    out = []
    for i in range(0, len(stems), batch):
        ims = [Image.open(ds.image_path(s)).convert('RGB') for s in stems[i:i + batch]]
        x = torch.stack([tf(im) for im in ims]).to(device)
        out.append(model(x).float().cpu().numpy())
    return np.concatenate(out)


def kid(X, Y, n_subsets=100, subset_size=100, seed=0):
    """Unbiased MMD^2 with the standard KID polynomial kernel, averaged over subsets."""
    rng = np.random.default_rng(seed)
    d = X.shape[1]
    subset_size = min(subset_size, len(X), len(Y))
    vals = []
    for _ in range(n_subsets):
        x = X[rng.choice(len(X), subset_size, replace=False)]
        y = Y[rng.choice(len(Y), subset_size, replace=False)]
        kxx = (x @ x.T / d + 1) ** 3
        kyy = (y @ y.T / d + 1) ** 3
        kxy = (x @ y.T / d + 1) ** 3
        m = subset_size
        np.fill_diagonal(kxx, 0); np.fill_diagonal(kyy, 0)
        vals.append(kxx.sum() / (m * (m - 1)) + kyy.sum() / (m * (m - 1)) - 2 * kxy.mean())
    v = np.array(vals)
    return float(v.mean()), float(v.std() / np.sqrt(len(v)))


def prdc(real, fake, k=5):
    """Precision / Recall / Density / Coverage (Naeem et al. 2020).

    Coverage is the term that matters for this project: the fraction of REAL
    samples with a synthetic neighbour. Precision (synthetic samples inside the
    real manifold) is reported but deliberately NOT optimized -- synthetic
    variability beyond the real distribution is desirable, not a defect.
    """
    def knn_radii(A, k):
        d = np.linalg.norm(A[:, None] - A[None], axis=-1)
        return np.sort(d, axis=1)[:, k]
    dr = knn_radii(real, k)
    df = knn_radii(fake, k)
    d_rf = np.linalg.norm(real[:, None] - fake[None], axis=-1)
    precision = (d_rf < dr[:, None]).any(0).mean()
    recall = (d_rf < df[None, :]).any(1).mean()
    density = (d_rf < dr[:, None]).sum(0).mean() / k
    coverage = (d_rf.min(1) < dr).mean()
    return dict(precision=float(precision), recall=float(recall),
                density=float(density), coverage=float(coverage))


def domain_auc(X, Y, seed=0):
    """Proxy A-distance: how separable are the two domains under a linear probe?

    AUC 0.5 = indistinguishable, 1.0 = trivially separable.
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_score
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import make_pipeline
    F = np.concatenate([X, Y])
    y = np.r_[np.zeros(len(X)), np.ones(len(Y))]
    clf = make_pipeline(StandardScaler(),
                        LogisticRegression(max_iter=2000, C=1.0, random_state=seed))
    return float(cross_val_score(clf, F, y, cv=5, scoring='roc_auc').mean())


def object_crops(ds, model, tf, device, pad=0.45, max_crops=4000, seed=0, tile=98):
    """Embed a crop around every labelled box -- the input to the CCDM proxy."""
    from PIL import Image
    rng = np.random.default_rng(seed)
    crops = []
    for s in ds.stems:
        b = ds.boxes(s)
        if not len(b):
            continue
        im = Image.open(ds.image_path(s)).convert('RGB')
        W, H = im.size
        for (_c, cx, cy, w, h) in b:
            side = max(w * W, h * H) * (1 + 2 * pad)
            x0, y0 = cx * W - side / 2, cy * H - side / 2
            crops.append(im.crop((int(x0), int(y0), int(x0 + side), int(y0 + side)))
                           .resize((tile, tile), Image.LANCZOS))
    if len(crops) > max_crops:
        crops = [crops[i] for i in rng.choice(len(crops), max_crops, replace=False)]
    return embed_images(crops, model, tf, device)


def ccdm(real_crops, syn_crops, **kw):
    """Class-conditioned domain match. Single class here, so this is MMD over
    object crops rather than whole scenes -- measuring the gap where the
    detector actually looks."""
    return kid(real_crops, syn_crops, **kw)
