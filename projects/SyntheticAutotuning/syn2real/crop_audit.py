"""Phase 0: crop every labelled box into contact sheets + draw boxes on full frames.

Answers the question the whole plan hinges on: does class 0 mean 'open flower' or
'any flower structure incl. buds', and does it mean the same thing on both sides?
"""
import os, sys, random
import numpy as np
from PIL import Image, ImageDraw

def load_labels(path):
    out = []
    for line in open(path):
        p = line.split()
        if len(p) == 5:
            out.append((int(p[0]), *map(float, p[1:])))
    return out

def contact_sheet(img_dir, lbl_dir, out_png, n_crops=64, tile=104, pad=0.45, seed=0):
    rng = random.Random(seed)
    files = sorted(os.listdir(img_dir))
    rng.shuffle(files)
    crops, tags = [], []
    for f in files:
        lp = os.path.join(lbl_dir, os.path.splitext(f)[0] + '.txt')
        if not os.path.exists(lp):
            continue
        boxes = load_labels(lp)
        if not boxes:
            continue
        im = Image.open(os.path.join(img_dir, f)).convert('RGB')
        W, H = im.size
        for (_c, cx, cy, w, h) in boxes:
            # square crop around the box so aspect is preserved and context is visible
            side = max(w * W, h * H) * (1 + 2 * pad)
            x0, y0 = cx * W - side / 2, cy * H - side / 2
            crops.append(im.crop((int(x0), int(y0), int(x0 + side), int(y0 + side)))
                           .resize((tile, tile), Image.LANCZOS))
            tags.append((f, cx, cy, w, h))
            if len(crops) >= n_crops:
                break
        if len(crops) >= n_crops:
            break
    cols = 8
    rows = (len(crops) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * (tile + 4) + 4, rows * (tile + 4) + 4), (24, 24, 28))
    for i, c in enumerate(crops):
        sheet.paste(c, (4 + (i % cols) * (tile + 4), 4 + (i // cols) * (tile + 4)))
    sheet.save(out_png)
    return len(crops), tags

def annotate(img_dir, lbl_dir, out_png, names, cols=2, scale=1.0):
    ims = []
    for f in names:
        im = Image.open(os.path.join(img_dir, f)).convert('RGB')
        W, H = im.size
        d = ImageDraw.Draw(im)
        for (_c, cx, cy, w, h) in load_labels(os.path.join(lbl_dir, os.path.splitext(f)[0] + '.txt')):
            x0, y0 = (cx - w / 2) * W, (cy - h / 2) * H
            x1, y1 = (cx + w / 2) * W, (cy + h / 2) * H
            for k in range(3):  # thick, high-contrast outline
                d.rectangle([x0 - k, y0 - k, x1 + k, y1 + k], outline=(255, 40, 40))
        ims.append(im)
    w0, h0 = ims[0].size
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * (w0 + 6) + 6, rows * (h0 + 6) + 6), (24, 24, 28))
    for i, im in enumerate(ims):
        sheet.paste(im, (6 + (i % cols) * (w0 + 6), 6 + (i // cols) * (h0 + 6)))
    if scale != 1.0:
        sheet = sheet.resize((int(sheet.width * scale), int(sheet.height * scale)), Image.LANCZOS)
    sheet.save(out_png)

if __name__ == '__main__':
    for tag in ('real', 'synthetic'):
        n, _ = contact_sheet(f'{tag}/images', f'{tag}/labels', f'audit/crops_{tag}.png')
        print(f'{tag}: {n} crops -> audit/crops_{tag}.png')

def annotated_frames():
    import random
    for tag, cols, sc in (('real', 2, 0.8), ('synthetic', 2, 0.8)):
        fs = sorted(os.listdir(f'{tag}/images'))
        rng = random.Random(7); rng.shuffle(fs)
        annotate(f'{tag}/images', f'{tag}/labels', f'audit/frames_{tag}.png', fs[:4], cols, sc)
        print(f'audit/frames_{tag}.png')
