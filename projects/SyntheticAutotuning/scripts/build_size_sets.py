"""Develop and tile the object-size sweep."""
import glob, json, os, subprocess, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from syn2real.tile import tile_frame
from syn2real import camera_pipeline as cp
rep={}
for d in sorted(glob.glob("frames_size/size*")):
    name=os.path.basename(d); dev=f"{d}_dev"
    subprocess.run([sys.executable,"scripts/develop.py",d,"--out",dev,"--target-L",str(cp.REAL_FOLIAGE_L)],check=True,capture_output=True)
    out=f"synthetic_{name}"; os.system(f"rm -rf {out}")
    w=[]
    for i,img in enumerate(sorted(glob.glob(os.path.join(dev,"*_RGB.jpeg")))):
        stem=os.path.basename(img).replace("camA_","").replace("_RGB.jpeg","")
        lab=os.path.join(d,stem+"_bbox.txt")
        if not os.path.exists(lab): continue
        w+=tile_frame(img,lab,out,n_tiles=30,seed=6000+i,
                      rover_mask_path=os.path.join(d,"camA_"+stem+"_rover.txt"),
                      ground_mask_path=os.path.join(d,"camA_"+stem+"_ground.txt"))
    box=np.array([t[2] for t in w]); cov=np.array([t[1] for t in w])
    # Object size actually achieved, in tile pixels, from the written labels.
    sizes=[]
    for f in glob.glob(os.path.join(out,"labels","*.txt")):
        for l in open(f):
            p=l.split()
            if len(p)>=5 and float(p[3])>0 and float(p[4])>0:
                sizes.append(np.sqrt(float(p[3])*640*float(p[4])*640))
    rep[name]=dict(tiles=len(w),boxes=int(box.sum()),boxes_per_tile=float(box.mean()),
                   cover_p50=float(np.median(cov)),size_p50=float(np.median(sizes)) if sizes else 0.0)
    print(f"{name:10s} {len(w):4d} tiles  {int(box.sum()):5d} boxes  {box.mean():5.2f}/tile  "
          f"obj {rep[name]['size_p50']:5.1f}px  cover {np.median(cov):.3f}",flush=True)
json.dump(rep,open("audit/size_sets.json","w"),indent=1)
print("REAL: 7.57 boxes/tile, object 33.0 px")
print("BUILD COMPLETE")
