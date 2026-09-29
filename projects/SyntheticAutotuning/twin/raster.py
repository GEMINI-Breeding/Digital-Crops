"""Run the label rasterizer in main.cpp and read its maps back.

`raster(...)` runs `SyntheticAutotuning raster` with a config, a seed and overrides and returns
the maps as numpy arrays registered to the (undistorted) real frame. The binary is CPU-only
for this mode, so it runs on the login node and on any CPU partition.
"""
import json
import os
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HELIOS = os.path.dirname(os.path.dirname(PROJECT))
BINARY = os.environ.get("TWIN_BINARY", os.path.join(PROJECT, "build", "SyntheticAutotuning"))
CONFIG = "../config/baseline.cfg"

CLASS_GROUND, CLASS_LEAF, CLASS_FLOWER_OPEN, CLASS_FLOWER_CLOSED, CLASS_STEM, CLASS_FRUIT, CLASS_ROVER, CLASS_NONE = 0, 1, 2, 3, 4, 5, 6, 255
VEG_CLASSES = (CLASS_LEAF, CLASS_FLOWER_OPEN, CLASS_FLOWER_CLOSED, CLASS_STEM, CLASS_FRUIT)

#: map name -> (numpy dtype, channels, file suffix written by main.cpp)
DTYPES = {"site": ("u2", 1, "u16"), "obj": ("u4", 1, "u32"), "class": ("u1", 1, "u8"), "depth": ("f4", 1, "f32"), "normal": ("f4", 3, "f32")}


class Maps:
    """The rasterizer's output for one scene."""

    def __init__(self, folder, base):
        self.meta = json.load(open(os.path.join(folder, base + "_raster.json")))
        self.folder, self.base = folder, base
        h, w = self.meta["crop_h"], self.meta["crop_w"]
        self.x0, self.y0 = self.meta["crop_x0"], self.meta["crop_y0"]
        self.W, self.H = self.meta["W"], self.meta["H"]
        self.arrays = {}
        for name, (dt, ch, suffix) in DTYPES.items():
            path = os.path.join(folder, f"{base}_{name}.{suffix}")
            a = np.fromfile(path, dtype=np.dtype("<" + dt))
            self.arrays[name] = a.reshape(h, w, ch) if ch > 1 else a.reshape(h, w)

    def __getattr__(self, name):
        if name in DTYPES:
            return self.arrays[name]
        raise AttributeError(name)

    @property
    def vegetation(self):
        return np.isin(self.arrays["class"], VEG_CLASSES)

    def full(self, name, fill=0):
        """Place a cropped map back into the full frame."""
        a = self.arrays[name]
        out = np.full((self.H, self.W) + a.shape[2:], fill, dtype=a.dtype)
        out[self.y0 : self.y0 + a.shape[0], self.x0 : self.x0 + a.shape[1]] = a
        return out

    def sites(self):
        """SITE lines printed by the binary, if `run` stored them."""
        p = os.path.join(self.folder, self.base + "_sites.txt")
        return read_sites(p) if os.path.exists(p) else []


def read_sites(path):
    out = []
    for line in open(path):
        t = line.split()
        if len(t) >= 7 and t[0] == "SITE":
            out.append(dict(index=int(t[1]), x=float(t[2]), y=float(t[3]), yaw_deg=float(t[4]), age=float(t[5]), seed=int(t[6]), plantID=int(t[7])))
    return out


def f32(x):
    """Shortest decimal that round-trips through float32, which is what the binary parses.

    The plant model is sensitive to its base position at the last bit: a leaf whose tip rests on
    the ground is clipped or kept depending on a comparison that a one-ULP move can flip. A
    layout must therefore name the position the plant was actually grown at, not a 4-decimal
    approximation of it, or the plant it reproduces is not the plant that was scored.
    """
    return f"{float(np.float32(x)):.9g}"


def write_layout(path, sites):
    """Layout file for canopy.layout_file: one `x y yaw_deg age seed` per plant."""
    with open(path, "w") as f:
        f.write("# x y yaw_deg age_days seed\n")
        for s in sites:
            f.write(f"{f32(s['x'])} {f32(s['y'])} {f32(s['yaw_deg'])} {f32(s['age'])} {int(s['seed'])}\n")


def run(overrides, seed=1, folder=None, base=None, config=CONFIG, binary=BINARY, timeout=1800, read_maps=True):
    """Rasterize one scene. Returns Maps (or the stdout string when read_maps is False, as in the
    per-site batch mode where the maps are named <base>_s<k>). `overrides` maps config key -> value."""
    folder = os.path.abspath(folder or os.path.join(PROJECT, "twin_work", "raster"))
    os.makedirs(folder, exist_ok=True)
    base = base or f"raster_{seed:07d}"
    ov = dict(overrides)
    if "canopy.layout_file" in ov:
        ov["canopy.layout_file"] = os.path.abspath(ov["canopy.layout_file"])  # the binary runs from build/
    ov["output.folder"] = folder + "/"
    ov["output.basename"] = base
    cmd = [binary, "raster", config, str(seed)] + [str(x) for kv in ov.items() for x in kv]
    # One thread per process. The binary links OpenMP and, left to itself, every raster process
    # spawns a thread per core; a pool of them then oversubscribes the node twenty-fold (64
    # plants across four processes: 24.7 s with the default, 1.2 s with one thread each). The
    # callers parallelise across processes, so the threads buy nothing.
    # A binary older than what it is built from is a stale build, and a stale one does not announce itself. Two ways
    # this has actually bitten: the default TWIN_BINARY is `build/`, which was a week out of date and quietly ignored
    # raster.each_site; and an interrupted build left build-cpu2's executable and libhelios.a weeks older than its own
    # object files while `make` still reported the target built. Checking main.cpp alone missed the second, because the
    # executable was newer than main.cpp and older than the Helios it links, so the whole dependency is checked here.
    newest_source, newest_path = 0.0, ""
    for root in (os.path.join(PROJECT, "main.cpp"), os.path.join(HELIOS, "core", "src"), os.path.join(HELIOS, "core", "include"),
                 os.path.join(HELIOS, "plugins", "plantarchitecture", "src"), os.path.join(HELIOS, "plugins", "radiation", "src"),
                 os.path.join(HELIOS, "plugins", "leafoptics", "src")):
        if os.path.isfile(root):
            candidates = [root]
        elif os.path.isdir(root):
            candidates = [os.path.join(root, f) for f in os.listdir(root) if f.endswith((".cpp", ".h", ".cu", ".cuh"))]
        else:
            continue
        for f in candidates:
            t = os.path.getmtime(f)
            if t > newest_source:
                newest_source, newest_path = t, f
    stamp = lambda t: time.strftime("%m-%d %H:%M", time.localtime(t))
    if newest_source and os.path.getmtime(binary) < newest_source:
        raise RuntimeError(f"{binary} ({stamp(os.path.getmtime(binary))}) is older than {os.path.relpath(newest_path, HELIOS)} "
                           f"({stamp(newest_source)}); rebuild it, or point TWIN_BINARY at a current build.")
    env = dict(os.environ, OMP_NUM_THREADS="1")
    r = subprocess.run(cmd, cwd=os.path.dirname(binary), capture_output=True, text=True, timeout=timeout, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"raster failed ({r.returncode}):\n{' '.join(cmd)}\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}")
    # WARNING/ERROR lines are kept alongside the SITE and DIAG lines: the binary warned on every run for months that it
    # could not transform primitives inside a compound object -- the per-plant yaw rotation silently moving no stalk --
    # and the filter here threw that line away, so nobody saw it until the plants were measured organ by organ.
    with open(os.path.join(folder, base + "_sites.txt"), "w") as f:
        for line in r.stdout.splitlines():
            if line.startswith("SITE ") or line.startswith("DIAG ") or "WARNING" in line or "ERROR" in line:
                f.write(line + "\n")
    if not read_maps:
        return r.stdout
    m = Maps(folder, base)
    m.stdout = r.stdout
    return m


def diag(stdout):
    """Parse `DIAG key=value ...` lines into a dict (last value wins)."""
    out = {}
    for line in stdout.splitlines():
        if not line.startswith("DIAG"):
            continue
        for tok in line.split()[1:]:
            if "=" in tok:
                k, v = tok.split("=", 1)
                try:
                    out[k] = float(v)
                except ValueError:
                    out[k] = v
    return out


# ---------------------------------------------------------------- batches ---

def _batch_job(args):
    ov, cands, workdir, base, with_maps = args
    layout = os.path.join(workdir, base + "_layout.txt")
    write_layout(layout, cands)
    o = dict(ov)
    o.update({"canopy.layout_file": layout, "raster.each_site": 1, "raster.ground": 0})
    stdout = run(o, seed=1, folder=workdir, base=base, read_maps=False)
    out = []
    for k in range(len(cands)):
        if not os.path.exists(os.path.join(workdir, f"{base}_s{k}_raster.json")):
            tail = "\n".join(stdout.splitlines()[-15:])
            raise RuntimeError(f"raster batch {base} in {workdir} exited cleanly but wrote no maps for site {k} of {len(cands)} ({cands[k]}); last output:\n{tail}")
        m = Maps(workdir, f"{base}_s{k}")
        if with_maps:
            out.append((m.vegetation.copy(), m.x0, m.y0, m.obj.copy(), m.arrays["class"].copy()))
        else:
            out.append((m.vegetation.copy(), m.x0, m.y0))
        for name, (dt, ch, suffix) in DTYPES.items():
            try:
                os.remove(os.path.join(workdir, f"{base}_s{k}_{name}.{suffix}"))
            except OSError:
                pass
        try:
            os.remove(os.path.join(workdir, f"{base}_s{k}_raster.json"))
        except OSError:
            pass
    for extra in (layout, os.path.join(workdir, base + "_sites.txt")):
        try:
            os.remove(extra)
        except OSError:
            pass
    return out


def rasterize_many(ov, cands, workdir, workers=8, chunk=24, tag="b", with_maps=False):
    """cands: list of dicts (x, y, yaw_deg, age, seed). Returns [(veg_crop, x0, y0)] in order, or with `with_maps`
    [(veg_crop, x0, y0, obj_crop, class_crop)] (the per-leaflet object map and the class map, for leaf-level measures)."""
    os.makedirs(workdir, exist_ok=True)
    chunks = [cands[i : i + chunk] for i in range(0, len(cands), chunk)]
    args = [(ov, c, workdir, f"{tag}{i}", with_maps) for i, c in enumerate(chunks)]
    if workers <= 1 or len(chunks) == 1:
        res = [_batch_job(a) for a in args]
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            res = list(ex.map(_batch_job, args))
    return [x for r in res for x in r]
