"""Tier-2: train on synthetic, evaluate detection mAP on held-out real imagery.

This is the only measurement in the project that is not a proxy. Everything else -- Tier-0
scalars, the asymmetric objective, KID, domain AUC -- is a stand-in for whether a detector trained
on synthetic data works on real data, and several of those stand-ins have already been shown to be
misleading. Where this disagrees with them, this is right.

Two design points that decide whether the numbers mean anything:

*Splitting.* The real set is 263 tiles over 58 genotypes and two dates, and tiles cut from one
frame share almost all of their content. Splitting at random would put near-duplicates on both
sides and inflate every score. Whole (date, genotype) groups go to one side or the other.

*Size control.* The original baseline has 1,307 tiles against 120 for the current build, and a
detector trained on ten times the data wins for reasons that have nothing to do with the domain
gap. Training sets are subsampled to a common size; the full baseline is reported separately as a
reference rather than compared directly.
"""

from __future__ import annotations

import os
import random
import re
import shutil

REAL_KEY = re.compile(r"Davis_(\d{8})\d*_.*?_(MAGIC\d+)_T\d+")


def group_key(filename):
    """(date, genotype) for a real tile; None if the name does not carry them."""
    m = REAL_KEY.search(filename)
    return (m.group(1), m.group(2)) if m else None


def split_real(real_root="real", test_fraction=0.4, seed=0):
    """Partition real tiles into train/test by whole (date, genotype) groups."""
    images = sorted(os.listdir(os.path.join(real_root, "images")))
    groups = {}
    for name in images:
        key = group_key(name)
        if key is None:
            raise ValueError(f"real tile name does not encode date and genotype: {name}")
        groups.setdefault(key, []).append(name)

    keys = sorted(groups)
    random.Random(seed).shuffle(keys)
    test, n_target = [], test_fraction * len(images)
    for key in keys:
        if len(test) >= n_target:
            break
        test.extend(groups[key])
    train = [n for n in images if n not in set(test)]
    return train, test


def _link(src_dir, names, dst_dir):
    os.makedirs(os.path.join(dst_dir, "images"), exist_ok=True)
    os.makedirs(os.path.join(dst_dir, "labels"), exist_ok=True)
    for name in names:
        stem = os.path.splitext(name)[0]
        for sub, ext in (("images", os.path.splitext(name)[1]), ("labels", ".txt")):
            src = os.path.abspath(os.path.join(src_dir, sub, stem + ext))
            dst = os.path.join(dst_dir, sub, stem + ext)
            if os.path.exists(src) and not os.path.exists(dst):
                os.symlink(src, dst)


def build_dataset(work_dir, train_specs, test_spec, seed=0):
    """Assemble a YOLO dataset directory from (root, names) specs and write its data.yaml.

    `train_specs` is a list of (root, names); several can be combined, which is how the
    synthetic-plus-k-real conditions are built.
    """
    shutil.rmtree(work_dir, ignore_errors=True)
    for root, names in train_specs:
        _link(root, names, os.path.join(work_dir, "train"))
    _link(test_spec[0], test_spec[1], os.path.join(work_dir, "val"))

    yaml_path = os.path.join(work_dir, "data.yaml")
    with open(yaml_path, "w") as f:
        f.write(f"path: {os.path.abspath(work_dir)}\n"
                "train: train/images\n"
                "val: val/images\n"
                "nc: 1\n"
                "names: [flower]\n")
    return yaml_path


def sample(root, n, seed=0):
    """n image names from a set, or all of them if it holds fewer."""
    names = sorted(os.listdir(os.path.join(root, "images")))
    if n is None or n >= len(names):
        return names
    return random.Random(seed).sample(names, n)


def train_eval(yaml_path, name, weights="weights/yolo11n.pt", epochs=60, imgsz=640,
               project="tier2_runs", seed=0):
    """Fine-tune a detector and return mAP on the val split defined by the data.yaml."""
    from ultralytics import YOLO

    model = YOLO(weights)
    model.train(data=yaml_path, epochs=epochs, imgsz=imgsz, batch=16, seed=seed,
                project=project, name=name, exist_ok=True, verbose=False, plots=False,
                pretrained=True, deterministic=True)
    metrics = model.val(data=yaml_path, split="val", project=project, name=name + "_val",
                        exist_ok=True, verbose=False, plots=False)
    return {"mAP50": float(metrics.box.map50), "mAP50-95": float(metrics.box.map)}
