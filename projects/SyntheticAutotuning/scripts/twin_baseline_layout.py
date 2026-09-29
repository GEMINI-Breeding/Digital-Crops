"""Naive baseline layout for a frame: no detection, no fitting.

Two rows at a nominal 0.76 m (30 in) centred in the frame, 0.15 m in-row spacing, 80 %
germination (hashed per site, so the stand is fixed per frame), one uniform age from an assumed
planting date of 2023-05-31 (no planting date is recorded for the 2023 Davis trial), random yaw.
Positions are written in bed coordinates for the rover calibration's camera at the nominal 1.5 m.
usage: twin_baseline_layout.py <out_workdir> <date>
"""
import datetime
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import twin.raster as TR  # noqa: E402

PLANTING = datetime.date(2023, 5, 31)
ROW_SPACING, INROW, GERMINATION, HALF_LENGTH = 0.76, 0.15, 0.80, 1.0

out, date = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
age = float((datetime.date.fromisoformat(date) - PLANTING).days)


def u(*key):
    h = hashlib.sha256(("baseline:" + ":".join(map(str, key))).encode()).digest()
    return int.from_bytes(h[:8], "little") / 2**64


sites = []
n = int(round(2 * HALF_LENGTH / INROW)) + 1
for r, x in enumerate((-ROW_SPACING / 2, ROW_SPACING / 2)):
    for j in range(n):
        if u(date, r, j, "germ") >= GERMINATION:
            continue
        sites.append(dict(x=x, y=-HALF_LENGTH + j * INROW, yaw_deg=360.0 * u(date, r, j, "yaw"), age=age,
                          seed=1 + int(u(date, r, j, "seed") * 2147483645)))
TR.write_layout(os.path.join(out, "layout.txt"), sites)
print(f"{out}: {len(sites)} plants, age {age:.0f} d (planting assumed {PLANTING})")
