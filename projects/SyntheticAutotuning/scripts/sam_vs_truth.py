"""Does SAM measure synthetic leaves correctly? Check it where the truth is known.

SAM says synthetic leaf major axis is 60 px against a real 75.9, and that the synthetic figure
plateaus at 60 however much the canopy is opened or the scale parameter raised. Extrapolating the
scale->size mapping from that plateau implies leaves of 26-47 cm to reach the real value, which no
cowpea has -- so either the mapping is not what it appears, or SAM under-reads synthetic leaves.

The renderer knows the answer. The geom pass labels every leaf and writes its bounding box, so the
same scene can be measured both ways: truth from the labels, and SAM from the rendered image. This
is the discipline that caught the Excess Green ground classifier -- check an inferential measure on
the domain where ground truth exists before trusting its cross-domain verdict.

Note the two are not the same quantity. A label box is axis-aligned around the whole visible leaf; a
SAM mask's fitted ellipse follows the leaf. For an ellipse inscribed in its box the mask area is
pi/4 of the box area, so sqrt(area) runs about 0.89 of sqrt(box area). Both are reported.
"""
import glob, json, os, subprocess, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real import camera_pipeline as cp
from syn2real.geom_io import read_boxes
from syn2real.tile import tile_frame

SEED = 9400
BASE = json.load(open("audit/phase5_confirm.json"))["results"]["18"]["overrides"]
LEAF = {"leaf.prototype_scale_min": "0.1369", "leaf.prototype_scale_max": "0.2467"}

ov = dict(BASE); ov.update(LEAF)

# --- truth: the geom pass labels every leaf ------------------------------------------------------
os.system("rm -rf svt_geom")
args = ["./SyntheticAutotuning", "geom", "../config/baseline.cfg", str(SEED),
        "leaf.use_obj_mesh", "1", "geom.label_leaves", "1",
        "output.folder", "../svt_geom/"]
for k, v in ov.items():
    args += [k, v]
print("running geom pass with scanned meshes (slow: ~30 min)", flush=True)
r = subprocess.run(args, capture_output=True, text=True, cwd="build-gpu")
if r.returncode != 0:
    raise SystemExit(f"geom failed: {(r.stderr.strip().splitlines() or ['?'])[-1]}")
run_dir = os.path.join("svt_geom", sorted(os.listdir("svt_geom"))[-1])
boxes = read_boxes(run_dir)
leaves = boxes[boxes["name"] == "leaf"]
if len(leaves) == 0:
    raise SystemExit("geom pass labelled no leaves; was geom.label_leaves set?")
truth_sqrt = np.sqrt(leaves["w"] * leaves["h"])
truth_major = np.maximum(leaves["w"], leaves["h"])
print(f"\nTRUTH from labels: {len(leaves)} leaves")
print(f"  sqrt(box area)  p50 {np.median(truth_sqrt):5.1f}  p90 {np.percentile(truth_sqrt,90):5.1f}")
print(f"  box major axis  p50 {np.median(truth_major):5.1f}  p90 {np.percentile(truth_major,90):5.1f}",
      flush=True)

# --- SAM on the rendered image of the SAME scene -------------------------------------------------
os.system("rm -rf svt_raw svt_dev svt_tiles")
flat = [x for kv in ov.items() for x in kv]
r = subprocess.run(["./SyntheticAutotuning", "render", "../config/baseline.cfg", str(SEED),
                    "camera.samples", "50", "output.folder", "../svt_raw/"] + flat,
                   capture_output=True, text=True, cwd="build-gpu")
if r.returncode != 0:
    raise SystemExit(f"render failed: {(r.stderr.strip().splitlines() or ['?'])[-1]}")
subprocess.run(["env/bin/python", "scripts/develop.py", "svt_raw", "--out", "svt_dev",
                "--target-L", str(cp.REAL_FOLIAGE_L)], check=True, capture_output=True)
for i, img in enumerate(sorted(glob.glob("svt_dev/*_RGB.jpeg"))):
    stem = os.path.basename(img).replace("camA_", "").replace("_RGB.jpeg", "")
    label = os.path.join("svt_raw", stem + "_bbox.txt")
    if not os.path.exists(label):
        continue
    tile_frame(img, label, "svt_tiles", n_tiles=15, seed=6900 + i,
               rover_mask_path=os.path.join("svt_raw", "camA_" + stem + "_rover.txt"),
               ground_mask_path=os.path.join("svt_raw", "camA_" + stem + "_ground.txt"))

os.environ.pop("YOLO_OFFLINE", None); os.environ.pop("ULTRALYTICS_OFFLINE", None)
from ultralytics import SAM
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sam_leaf_size import leaf_masks
sam = SAM("weights/mobile_sam.pt")
rows = []
for f in sorted(glob.glob("svt_tiles/images/*.jpeg")):
    rows += leaf_masks(sam, f)
a = np.array(rows)
print(f"\nSAM on the same scene: {len(rows)} leaf masks")
print(f"  sqrt(mask area) p50 {np.median(a[:,0]):5.1f}  p90 {np.percentile(a[:,0],90):5.1f}")
print(f"  ellipse major   p50 {np.median(a[:,1]):5.1f}  p90 {np.percentile(a[:,1],90):5.1f}")

print(f"\n{'quantity':>22} {'truth':>8} {'SAM':>8} {'SAM/truth':>10}")
print(f"{'sqrt area (px)':>22} {np.median(truth_sqrt)*0.886:8.1f} {np.median(a[:,0]):8.1f} "
      f"{np.median(a[:,0])/(np.median(truth_sqrt)*0.886):10.2f}   (truth scaled by pi/4 for shape)")
print(f"{'major axis (px)':>22} {np.median(truth_major):8.1f} {np.median(a[:,1]):8.1f} "
      f"{np.median(a[:,1])/np.median(truth_major):10.2f}")
print(f"\nreal leaves measure 75.9 px major by the SAM path")
json.dump(dict(truth_sqrt_p50=float(np.median(truth_sqrt)),
               truth_major_p50=float(np.median(truth_major)),
               sam_sqrt_p50=float(np.median(a[:, 0])), sam_major_p50=float(np.median(a[:, 1])),
               n_truth=int(len(leaves)), n_sam=int(len(rows))),
          open("audit/sam_vs_truth.json", "w"), indent=1)
os.system("rm -rf svt_geom svt_raw svt_dev svt_tiles")
print("SAM VS TRUTH COMPLETE")
