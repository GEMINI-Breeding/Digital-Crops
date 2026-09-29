"""Rebuild the section-08 tile strip from a tiled set.

Tiles are chosen by vegetation-cover percentile (25th, 50th, 75th) rather than by eye, so the strip
is a fair sample of the set rather than three tiles that happened to look good.
"""
import base64, glob, os, sys
import cv2, numpy as np

TILE_PX, N = 200, 3


def cover(rgb):
    f = rgb.astype(np.float32) / 255.0
    s = f.sum(2) + 1e-6
    return float(np.mean(2 * f[:, :, 1] / s - f[:, :, 0] / s - f[:, :, 2] / s > 0.05))


def build(src_dir):
    files = sorted(glob.glob(os.path.join(src_dir, "images", "*.jpg")) +
                   glob.glob(os.path.join(src_dir, "images", "*.jpeg")))
    if not files:
        raise SystemExit(f"no tiles under {src_dir}")
    covers = []
    for f in files:
        bgr = cv2.imread(f)
        covers.append((cover(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)), f))
    covers.sort()
    picks = [covers[int(q * (len(covers) - 1))] for q in (0.25, 0.50, 0.75)]
    panels = []
    for c, f in picks:
        bgr = cv2.imread(f)
        panels.append(cv2.resize(bgr, (TILE_PX, TILE_PX), interpolation=cv2.INTER_AREA))
        print(f"  {os.path.basename(f)}  cover={c:.3f}")
    strip = np.hstack(panels)
    ok, buf = cv2.imencode(".jpg", strip, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    if not ok:
        raise SystemExit("encode failed")
    return base64.b64encode(buf.tobytes()).decode("ascii")


if __name__ == "__main__":
    b64 = build(sys.argv[1] if len(sys.argv) > 1 else "synthetic_v17")
    open("audit/strip_v17.b64", "w").write(b64)
    print(f"wrote audit/strip_v17.b64  ({len(b64)/1024:.0f} KB)")
