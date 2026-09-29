"""Show the hand labels and the SAM masks on the same crops, so the comparison can be eyeballed.

Left of each pair: the hand lines -- solid for fully visible, dashed for partial/edge-cut.
Right: SAM's mask outlines, coloured by whether a hand label lands inside (confirmed) or not.
"""
import json, os, sys
import numpy as np, cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from handlabel_vs_sam import tile_masks, CROP_DIR
import handlabel_vs_sam as H

WHOLE = (61, 179, 242)      # BGR amber
PART = (217, 195, 79)       # BGR cyan
CONF = (100, 220, 120)
EXTRA = (95, 122, 224)
SCALE = 2


def main():
    os.environ.pop("YOLO_OFFLINE", None); os.environ.pop("ULTRALYTICS_OFFLINE", None)
    import torch
    H.DEVICE = 0 if torch.cuda.is_available() else "cpu"
    from ultralytics import SAM
    model = SAM("weights/mobile_sam.pt")

    manifest = {r["file"]: r for r in json.load(open(f"{CROP_DIR}/manifest.json"))}
    labels = json.load(open(os.environ["SP"] + "/handlabels.json"))
    cache, rows = {}, []
    for fname in sorted(labels)[:6]:
        lines, rec = labels[fname], manifest[fname]
        src = "real/images/" + rec["source"]
        if src not in cache:
            cache[src] = tile_masks(model, src)
        X, Y, S = rec["x"], rec["y"], rec["size"]
        crop = cv2.imread(f"{CROP_DIR}/{fname}")
        left = cv2.resize(crop, (S*SCALE, S*SCALE), interpolation=cv2.INTER_LANCZOS4)
        right = left.copy()

        confirmed = set()
        for l in lines:
            if l["occluded"]:
                continue
            mx = int(round((l["x1"]+l["x2"])/2))+X; my = int(round((l["y1"]+l["y2"])/2))+Y
            cand = [i for i, m in enumerate(cache[src]) if m["mask"][my, mx]]
            if cand:
                confirmed.add(min(cand, key=lambda i: cache[src][i]["area"]))

        for i, m in enumerate(cache[src]):
            if not (m["x0"] >= X and m["x1"] < X+S and m["y0"] >= Y and m["y1"] < Y+S):
                continue
            sub = m["mask"][Y:Y+S, X:X+S].astype(np.uint8)
            cnt, _ = cv2.findContours(sub, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(right, [c*SCALE for c in cnt], -1,
                             CONF if i in confirmed else EXTRA, 2)

        for l in lines:
            p1 = (int(l["x1"]*SCALE), int(l["y1"]*SCALE))
            p2 = (int(l["x2"]*SCALE), int(l["y2"]*SCALE))
            if l["occluded"]:
                d = np.hypot(p2[0]-p1[0], p2[1]-p1[1]) or 1
                for t in np.arange(0, 1, 12/d):
                    q1 = (int(p1[0]+(p2[0]-p1[0])*t), int(p1[1]+(p2[1]-p1[1])*t))
                    t2 = min(1, t+6/d)
                    q2 = (int(p1[0]+(p2[0]-p1[0])*t2), int(p1[1]+(p2[1]-p1[1])*t2))
                    cv2.line(right if False else left, q1, q2, PART, 2, cv2.LINE_AA)
            else:
                cv2.line(left, p1, p2, WHOLE, 3, cv2.LINE_AA)
                for p in (p1, p2):
                    cv2.circle(left, p, 4, WHOLE, -1, cv2.LINE_AA)
        rows.append(np.hstack([left, np.full((S*SCALE, 8, 3), 40, np.uint8), right]))

    gap = np.full((10, rows[0].shape[1], 3), 40, np.uint8)
    out = rows[0]
    for r in rows[1:]:
        out = np.vstack([out, gap, r])
    out = cv2.resize(out, (out.shape[1]//2, out.shape[0]//2), interpolation=cv2.INTER_AREA)
    cv2.imwrite("audit/handlabel_panels.jpg", out, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    print(f"wrote audit/handlabel_panels.jpg {out.shape}")


if __name__ == "__main__":
    main()
