import os
import sys
import glob
import json
import subprocess
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np
import cv2

def run_single_simulation(task_info):
    """
    Worker function to execute C++ rendering for a single plot.
    """
    dap = task_info["dap"]
    bed = task_info["bed"]
    tier = task_info["tier"]
    f_path = task_info["path"]
    output_dir = task_info["output_dir"]
    sim_mode = task_info["sim_mode"]
    build_dir = task_info["build_dir"]
    binary_path = task_info["binary_path"]
    override_exposure = task_info.get("override_exposure", False)
    
    output_name = f"dap{dap}_plot_{bed}_{tier}_{sim_mode}"
    
    actual_json_path = f_path
    if override_exposure:
        try:
            with open(f_path, 'r') as f:
                data = json.load(f)
            if "camera" not in data:
                data["camera"] = {}
            if "sensor" not in data["camera"]:
                data["camera"]["sensor"] = {}
            data["camera"]["sensor"]["exposure_mode"] = "ISO"
            
            stem = os.path.splitext(os.path.basename(f_path))[0]
            modified_json_path = os.path.join(output_dir, f"{stem}_override.json")
            with open(modified_json_path, 'w') as f:
                json.dump(data, f, indent=4)
            actual_json_path = modified_json_path
        except Exception as e:
            print(f"Failed to apply overrides for {f_path}: {e}")
            
    # 1. Construct command
    cmd = [
        binary_path,
        "-f", actual_json_path,
        "-o", output_dir,
        "-n", output_name,
    ]
    
    if sim_mode == "vis":
        cmd.extend(["--renderer", "vis"])
    else:
        cmd.extend(["--renderer", "radiation"])

    cmd.extend(["--no-save-xml"])
    cmd.extend(["--temperature", "true"])
    cmd.extend(["--depth", "true"])
    cmd.extend(["--multispectral", "false"])
    
    exec_env = os.environ.copy()
    exec_env["DISPLAY"] = ":2.0"
    
    try:
        # Run C++ binary
        result = subprocess.run(cmd, cwd=build_dir, env=exec_env, check=True, capture_output=True, text=True)
        
        # Apply colormaps
        # Grayscale depth image: output_dir/output_name_0000_depth.jpeg
        depth_path = os.path.join(output_dir, f"{output_name}_0000_depth.jpeg")
        if os.path.exists(depth_path):
            depth_img = cv2.imread(depth_path, cv2.IMREAD_GRAYSCALE)
            if depth_img is not None:
                mask_bg = (depth_img > 220)
                mask_crop = ~mask_bg
                out_depth = np.zeros_like(depth_img, dtype=np.uint8)
                out_depth[mask_bg] = 255
                
                if np.any(mask_crop):
                    crop_vals = depth_img[mask_crop]
                    c_min, c_max = float(crop_vals.min()), float(crop_vals.max())
                    if c_max > c_min:
                        out_depth[mask_crop] = np.clip(((crop_vals - c_min) / (c_max - c_min)) * 220, 0, 220).astype(np.uint8)
                    else:
                        out_depth[mask_crop] = 100
                
                depth_colorized = cv2.applyColorMap(out_depth, cv2.COLORMAP_JET)
                cv2.imwrite(os.path.join(output_dir, f"{output_name}_0000_depth_jet.jpeg"), depth_colorized)
                
        # Grayscale temperature image: output_dir/output_name_0000_temperature.jpeg
        temp_path = os.path.join(output_dir, f"{output_name}_0000_temperature.jpeg")
        if os.path.exists(temp_path):
            temp_img = cv2.imread(temp_path, cv2.IMREAD_GRAYSCALE)
            if temp_img is not None:
                temp_inferno = cv2.applyColorMap(temp_img, cv2.COLORMAP_INFERNO)
                cv2.imwrite(os.path.join(output_dir, f"{output_name}_0000_temperature_inferno.jpeg"), temp_inferno)
                
        return {"bed": bed, "tier": tier, "status": "success", "error": None}
    except Exception as e:
        err_msg = str(e)
        if isinstance(e, subprocess.CalledProcessError):
            err_msg += f"\nSTDOUT:\n{e.stdout}\nSTDERR:\n{e.stderr}"
        return {"bed": bed, "tier": tier, "status": "failed", "error": err_msg}

def main():
    parser = argparse.ArgumentParser(description="Orchestrate isolated, plot-by-plot field simulations in parallel.")
    parser.add_argument("--dap", type=int, default=28, help="Days After Planting (DAP)")
    parser.add_argument("--start_bed", type=int, default=1, help="Start bed index")
    parser.add_argument("--end_bed", type=int, default=8, help="End bed index")
    parser.add_argument("--start_tier", type=int, default=1, help="Start tier index")
    parser.add_argument("--end_tier", type=int, default=14, help="End tier index")
    parser.add_argument("--method", type=str, default="Method4_+FewshotImages", help="Parameter optimization method")
    parser.add_argument("--sim_mode", type=str, default="radiation", choices=["radiation", "vis"], help="Simulation mode")
    parser.add_argument("--output_dir", type=str, default=None, help="Output folder")
    parser.add_argument("--num_workers", type=int, default=8, help="Number of parallel rendering processes")
    parser.add_argument("--override-exposure", action="store_true", help="Override camera exposure_mode to ISO to use the dynamic ISO and shutter speed with sun elevation correction instead of auto-exposure.")
    
    args = parser.parse_args()
    
    base_dir = "/home/lion397/codes/Image2PlantArchitecture_v2/notebooks/evaluation_results/2025_Davis_temperature_0/real_fewshot_real_image_rendered/gemma4_31b"
    
    if args.output_dir is None:
        args.output_dir = os.path.join(os.getcwd(), f"test_isolated_output_dap{args.dap}")
        
    os.makedirs(args.output_dir, exist_ok=True)
    
    # 2. Gather individual plot params files
    search_pattern = os.path.join(base_dir, f"dap_{args.dap}_plot_*_*_0000_{args.method}_0000_params.json")
    json_files = glob.glob(search_pattern)
    
    if not json_files:
        print(f"Cannot find specific method files for '{args.method}', falling back to general params pattern...")
        json_files = glob.glob(os.path.join(base_dir, f"dap_{args.dap}_plot_*_*_0000_params.json"))
        
    if not json_files:
        print(f"ERROR: Cannot find parameter JSON files for DAP {args.dap} in: {base_dir}")
        sys.exit(1)
        
    # Map to coordinates
    tasks = []
    for f_path in json_files:
        basename = os.path.basename(f_path)
        parts = basename.split("_")
        bed_idx = int(parts[3])
        tier_idx = int(parts[4])
        
        if args.start_bed <= bed_idx <= args.end_bed and args.start_tier <= tier_idx <= args.end_tier:
            tasks.append({
                "dap": args.dap,
                "bed": bed_idx,
                "tier": tier_idx,
                "path": f_path,
                "output_dir": args.output_dir,
                "sim_mode": args.sim_mode,
                "build_dir": os.path.join(os.getcwd(), "build_release"),
                "binary_path": "./main",
                "override_exposure": args.override_exposure
            })
            
    print(f"Found {len(tasks)} plot parameter files matching grid coordinates.")
    print(f"Launching process pool with {args.num_workers} parallel workers...")
    
    success_count = 0
    failed_tasks = []
    
    with ProcessPoolExecutor(max_workers=args.num_workers) as executor:
        futures = {executor.submit(run_single_simulation, task): task for task in tasks}
        
        for future in as_completed(futures):
            task = futures[future]
            res = future.result()
            if res["status"] == "success":
                success_count += 1
                print(f"[SUCCESS] Plot (Bed {res['bed']}, Tier {res['tier']}) rendered.")
            else:
                failed_tasks.append(res)
                print(f"[FAILED] Plot (Bed {res['bed']}, Tier {res['tier']}) failed: {res['error']}")
                
    print("\n==================================================")
    print(f"Render Execution Complete:")
    print(f"  Total Requested: {len(tasks)}")
    print(f"  Successful:      {success_count}")
    print(f"  Failed:          {len(failed_tasks)}")
    print("==================================================")
    
    if failed_tasks:
        sys.exit(1)

if __name__ == "__main__":
    main()
