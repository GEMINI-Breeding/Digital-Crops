import os
import sys
import json
import argparse
import glob
from PIL import Image
import numpy as np

def main():
    parser = argparse.ArgumentParser(description="Stitch isolated plot renders and annotations into unified maps.")
    parser.add_argument("--dap", type=int, default=28, help="Days After Planting (DAP)")
    parser.add_argument("--start_bed", type=int, default=1, help="Start bed index")
    parser.add_argument("--end_bed", type=int, default=8, help="End bed index")
    parser.add_argument("--start_tier", type=int, default=1, help="Start tier index")
    parser.add_argument("--end_tier", type=int, default=14, help="End tier index")
    parser.add_argument("--sim_mode", type=str, default="radiation", choices=["radiation", "vis"], help="Simulation mode")
    parser.add_argument("--input_dir", type=str, default=None, help="Folder containing isolated plot outputs")
    parser.add_argument("--output_dir", type=str, default=None, help="Folder to save unified output")
    parser.add_argument("--left_to_right_bed", type=lambda x: (str(x).lower() in ['true', '1', 'yes']), default=False, help="Bed ordering left to right")
    parser.add_argument("--bottom_to_top_tier", type=lambda x: (str(x).lower() in ['true', '1', 'yes']), default=True, help="Tier ordering bottom to top")
    parser.add_argument("--wait", type=lambda x: (str(x).lower() in ['true', '1', 'yes']), default=True, help="Wait for all expected files to exist before stitching")
    parser.add_argument("--poll_interval", type=int, default=15, help="Interval in seconds between polling checks")
    parser.add_argument("--wait_timeout", type=int, default=10800, help="Maximum seconds to wait before timeout")
    parser.add_argument("--rotate-real", type=float, default=1.0, help="Rotate the georeferenced real drone crop in degrees")
    
    args = parser.parse_args()
    
    if args.input_dir is None:
        args.input_dir = os.path.join(os.getcwd(), f"test_isolated_output_dap{args.dap}")
    if args.output_dir is None:
        args.output_dir = os.path.join(os.getcwd(), "test_merged_output")
        
    os.makedirs(args.output_dir, exist_ok=True)
    
    n_beds = args.end_bed - args.start_bed + 1
    n_tiers = args.end_tier - args.start_tier + 1
    
    print(f"Stitching {n_beds}x{n_tiers} field layout (dap {args.dap})...")
    
    # Wait/polling logic for distributed execution
    is_slurm = os.environ.get("SLURM_JOB_ID") is not None
    if args.wait and is_slurm:
        print("[INFO] Running within Slurm environment. Skipping active file polling since dependent jobs have already finished.")
    elif args.wait:
        import time
        expected_plots = []
        for bed in range(args.start_bed, args.end_bed + 1):
            for tier in range(args.start_tier, args.end_tier + 1):
                expected_plots.append((bed, tier))
                
        print(f"Waiting for parallel rendering jobs to finish. Total plots expected: {len(expected_plots)}")
        start_time = time.time()
        
        while True:
            missing_plots = []
            for bed, tier in expected_plots:
                prefix = f"dap{args.dap}_plot_{bed}_{tier}_{args.sim_mode}"
                required_files = [
                    os.path.join(args.input_dir, f"{prefix}_0000.jpeg"),
                    os.path.join(args.input_dir, f"{prefix}_0000_depth.jpeg"),
                    os.path.join(args.input_dir, f"{prefix}_0000_depth_jet.jpeg"),
                    os.path.join(args.input_dir, f"{prefix}_0000_temperature.jpeg"),
                    os.path.join(args.input_dir, f"{prefix}_0000_temperature_inferno.jpeg"),
                    os.path.join(args.input_dir, f"{prefix}_0000_masks.json"),
                    os.path.join(args.input_dir, f"{prefix}_0000_boxes.txt")
                ]
                
                completed = True
                for r_file in required_files:
                    if not os.path.exists(r_file) or os.path.getsize(r_file) == 0:
                        completed = False
                        break
                
                if not completed:
                    missing_plots.append((bed, tier))
                    
            if not missing_plots:
                print("[SUCCESS] All plot rendering files detected and ready!")
                break
                
            elapsed = time.time() - start_time
            if elapsed > args.wait_timeout:
                print(f"ERROR: Timeout reached waiting for rendering files. Missing {len(missing_plots)} plots.")
                sys.exit(1)
                
            print(f"[{int(elapsed)}s elapsed] Still waiting for {len(missing_plots)}/{len(expected_plots)} plots to complete. Next check in {args.poll_interval}s...")
            time.sleep(args.poll_interval)
    
    # 1. Auto-detect single plot resolution
    first_rgb_pattern = os.path.join(args.input_dir, f"dap{args.dap}_plot_*_*_{args.sim_mode}_0000.jpeg")
    rgb_files = glob.glob(first_rgb_pattern)
    if not rgb_files:
        print(f"ERROR: No rendered plot files found in input directory: {args.input_dir}")
        sys.exit(1)
        
    first_img = Image.open(rgb_files[0])
    plot_width, plot_height = first_img.size
    print(f"Detected single-plot resolution: {plot_width}x{plot_height} px.")
    
    # 2. Allocate canvas memory
    global_width = n_beds * plot_width
    global_height = n_tiers * plot_height
    print(f"Stitched global image resolution: {global_width}x{global_height} px.")
    
    global_rgb = Image.new("RGB", (global_width, global_height), (0, 0, 0))
    global_depth = Image.new("L", (global_width, global_height), 0)
    global_depth_jet = Image.new("RGB", (global_width, global_height), (0, 0, 0))
    global_temp = Image.new("L", (global_width, global_height), 0)
    global_temp_inferno = Image.new("RGB", (global_width, global_height), (0, 0, 0))
    
    # Global annotation holders
    global_coco = {
        "images": [{
            "file_name": f"merged_dap{args.dap}_bed{args.start_bed}to{args.end_bed}_tier{args.start_tier}to{args.end_tier}_{args.sim_mode}_0000.jpeg",
            "height": global_height,
            "id": 0,
            "width": global_width
        }],
        "annotations": [],
        "categories": []
    }
    
    global_boxes_yolo = []
    anno_id_counter = 0
    categories_set = False
    
    # 3. Stitch grid loop
    for bed in range(args.start_bed, args.end_bed + 1):
        for tier in range(args.start_tier, args.end_tier + 1):
            # Calculate row/col indices
            if args.left_to_right_bed:
                col = bed - args.start_bed
            else:
                col = n_beds - 1 - (bed - args.start_bed)
                
            if args.bottom_to_top_tier:
                row = n_tiers - 1 - (tier - args.start_tier)
            else:
                row = tier - args.start_tier
                
            x_offset = col * plot_width
            y_offset = row * plot_height
            
            prefix = f"dap{args.dap}_plot_{bed}_{tier}_{args.sim_mode}"
            
            # --- Stitch Images ---
            # RGB
            rgb_path = os.path.join(args.input_dir, f"{prefix}_0000.jpeg")
            if os.path.exists(rgb_path):
                img = Image.open(rgb_path)
                if img.size != (plot_width, plot_height):
                    img = img.resize((plot_width, plot_height), Image.Resampling.BILINEAR)
                global_rgb.paste(img, (x_offset, y_offset))
                
            # Depth Grayscale
            depth_path = os.path.join(args.input_dir, f"{prefix}_0000_depth.jpeg")
            if os.path.exists(depth_path):
                img = Image.open(depth_path)
                if img.size != (plot_width, plot_height):
                    img = img.resize((plot_width, plot_height), Image.Resampling.BILINEAR)
                global_depth.paste(img, (x_offset, y_offset))
                
            # Depth Jet
            depth_jet_path = os.path.join(args.input_dir, f"{prefix}_0000_depth_jet.jpeg")
            if os.path.exists(depth_jet_path):
                img = Image.open(depth_jet_path)
                if img.size != (plot_width, plot_height):
                    img = img.resize((plot_width, plot_height), Image.Resampling.BILINEAR)
                global_depth_jet.paste(img, (x_offset, y_offset))
                
            # Temp Grayscale
            temp_path = os.path.join(args.input_dir, f"{prefix}_0000_temperature.jpeg")
            if os.path.exists(temp_path):
                img = Image.open(temp_path)
                if img.size != (plot_width, plot_height):
                    img = img.resize((plot_width, plot_height), Image.Resampling.BILINEAR)
                global_temp.paste(img, (x_offset, y_offset))
                
            # Temp Inferno
            temp_inferno_path = os.path.join(args.input_dir, f"{prefix}_0000_temperature_inferno.jpeg")
            if os.path.exists(temp_inferno_path):
                img = Image.open(temp_inferno_path)
                if img.size != (plot_width, plot_height):
                    img = img.resize((plot_width, plot_height), Image.Resampling.BILINEAR)
                global_temp_inferno.paste(img, (x_offset, y_offset))
                
            # --- Stitch COCO Annotations ---
            coco_path = os.path.join(args.input_dir, f"{prefix}_0000_masks.json")
            if os.path.exists(coco_path):
                try:
                    with open(coco_path, "r") as f:
                        plot_coco = json.load(f)
                    
                    # Calculate scaling factors if the source plot resolution differs
                    actual_w, actual_h = plot_width, plot_height
                    if "images" in plot_coco and len(plot_coco["images"]) > 0:
                        actual_w = plot_coco["images"][0].get("width", plot_width)
                        actual_h = plot_coco["images"][0].get("height", plot_height)
                    elif os.path.exists(rgb_path):
                        with Image.open(rgb_path) as test_img:
                            actual_w, actual_h = test_img.size
                            
                    scale_x = plot_width / actual_w
                    scale_y = plot_height / actual_h
                    
                    if not categories_set and "categories" in plot_coco:
                        global_coco["categories"] = plot_coco["categories"]
                        categories_set = True
                        
                    if "annotations" in plot_coco:
                        for ann in plot_coco["annotations"]:
                            # Translate and scale bounding box
                            bbox = ann["bbox"] # [x_min, y_min, w, h]
                            new_bbox = [
                                (bbox[0] * scale_x) + x_offset, 
                                (bbox[1] * scale_y) + y_offset, 
                                bbox[2] * scale_x, 
                                bbox[3] * scale_y
                            ]
                            
                            # Translate and scale polygon segmentation points
                            new_segmentations = []
                            if "segmentation" in ann:
                                for seg in ann["segmentation"]:
                                    new_seg = []
                                    for i in range(0, len(seg), 2):
                                        new_seg.append((seg[i] * scale_x) + x_offset)
                                        new_seg.append((seg[i+1] * scale_y) + y_offset)
                                    new_segmentations.append(new_seg)
                                    
                            # Create unified annotation
                            unified_ann = dict(ann)
                            unified_ann["id"] = anno_id_counter
                            unified_ann["image_id"] = 0
                            unified_ann["bbox"] = new_bbox
                            unified_ann["segmentation"] = new_segmentations
                            
                            global_coco["annotations"].append(unified_ann)
                            anno_id_counter += 1
                except Exception as e:
                    print(f"[WARNING] Failed to parse COCO JSON for {prefix}: {e}")
                    
            # --- Stitch YOLO Bounding Boxes ---
            boxes_path = os.path.join(args.input_dir, f"{prefix}_0000_boxes.txt")
            if os.path.exists(boxes_path):
                try:
                    with open(boxes_path, "r") as f:
                        lines = f.readlines()
                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                        parts = line.split()
                        class_id = int(parts[0])
                        x_c_local = float(parts[1])
                        y_c_local = float(parts[2])
                        w_local = float(parts[3])
                        h_local = float(parts[4])
                        
                        # Convert to absolute pixel coordinates
                        x_abs = (x_c_local * plot_width) + x_offset
                        y_abs = (y_c_local * plot_height) + y_offset
                        w_abs = w_local * plot_width
                        h_abs = h_local * plot_height
                        
                        # Re-normalize to global canvas size
                        x_c_global = x_abs / global_width
                        y_c_global = y_abs / global_height
                        w_global = w_abs / global_width
                        h_global = h_abs / global_height
                        
                        global_boxes_yolo.append(f"{class_id} {x_c_global:.6f} {y_c_global:.6f} {w_global:.6f} {h_global:.6f}")
                except Exception as e:
                    print(f"[WARNING] Failed to parse YOLO boxes for {prefix}: {e}")
                    
    # 4. Save unified deliverables
    output_prefix = f"merged_dap{args.dap}_bed{args.start_bed}to{args.end_bed}_tier{args.start_tier}to{args.end_tier}_{args.sim_mode}"
    
    # Save Images
    global_rgb.save(os.path.join(args.output_dir, f"{output_prefix}_0000.jpeg"), "JPEG", quality=95)
    global_depth.save(os.path.join(args.output_dir, f"{output_prefix}_0000_depth.jpeg"), "JPEG")
    global_depth_jet.save(os.path.join(args.output_dir, f"{output_prefix}_0000_depth_jet.jpeg"), "JPEG")
    global_temp.save(os.path.join(args.output_dir, f"{output_prefix}_0000_temperature.jpeg"), "JPEG")
    global_temp_inferno.save(os.path.join(args.output_dir, f"{output_prefix}_0000_temperature_inferno.jpeg"), "JPEG")
    
    # Save Annotations
    with open(os.path.join(args.output_dir, f"{output_prefix}_0000_masks.json"), "w") as f:
        json.dump(global_coco, f, indent=2)
        
    with open(os.path.join(args.output_dir, f"{output_prefix}_0000_boxes.txt"), "w") as f:
        f.write("\n".join(global_boxes_yolo) + "\n")
        
    print("\n==================================================")
    print(f"[SUCCESS] Stitching execution completed successfully!")
    print(f"Stitched files saved in: {args.output_dir}")
    print(f"  RGB image:           {output_prefix}_0000.jpeg")
    print(f"  Depth (grayscale):   {output_prefix}_0000_depth.jpeg")
    print(f"  Depth (JET):         {output_prefix}_0000_depth_jet.jpeg")
    print(f"  Temp (grayscale):    {output_prefix}_0000_temperature.jpeg")
    print(f"  Temp (INFERNO):      {output_prefix}_0000_temperature_inferno.jpeg")
    print(f"  COCO masks JSON:     {output_prefix}_0000_masks.json ({len(global_coco['annotations'])} annotations)")
    print(f"  YOLO boxes TXT:      {output_prefix}_0000_boxes.txt ({len(global_boxes_yolo)} boxes)")
    print("==================================================")
    
    # 5. Crop Real Drone Orthophoto matching the plot grid envelope
    dap_to_tif = {
        10: "/home/lion397/GEMINI/heesup/dataset/2025_Davis/real_data/2025-06-06/Drone/2025-06-06-RGB.tif",
        28: "/home/lion397/GEMINI/heesup/dataset/2025_Davis/real_data/2025-06-24/2025-06-24-Drone-10m-RGB.tif",
        49: "/home/lion397/GEMINI/heesup/dataset/2025_Davis/real_data/2025-07-15/2025-07-15-RGB-10m.tif",
        70: "/home/lion397/GEMINI/heesup/dataset/2025_Davis/real_data/2025-08-05/2025-08-05-10m-RGB.tif",
        87: "/home/lion397/GEMINI/heesup/dataset/2025_Davis/real_data/2025-08-22/2025-08-22-10m-RGB.tif",
    }
    geojson_path = "/home/lion397/GEMINI/heesup/dataset/2025_Davis/Plot-Boundary-WGS84.geojson"
    ortho_path = dap_to_tif.get(args.dap)
    
    if not ortho_path or not os.path.exists(ortho_path):
        print(f"[WARNING] Real drone Ortho TIF not found for DAP {args.dap}: {ortho_path}")
    elif not os.path.exists(geojson_path):
        print(f"[WARNING] Plot boundary GeoJSON not found: {geojson_path}")
    else:
        try:
            print(f"\n==================================================")
            print(f"Cropping Real Drone Orthophoto for DAP {args.dap}")
            print(f"==================================================")
            import geopandas as gpd
            import rasterio
            from rasterio.mask import mask
            from shapely.geometry import mapping, box
            
            gdf = gpd.read_file(geojson_path)
            # Find plots matching grid (column is bed, row is tier)
            target_plots = gdf[(gdf['column'] >= args.start_bed) & (gdf['column'] <= args.end_bed) & 
                               (gdf['row'] >= args.start_tier) & (gdf['row'] <= args.end_tier)]
            
            if len(target_plots) > 0:
                with rasterio.open(ortho_path) as src:
                    ortho_crs = src.crs
                    if gdf.crs != ortho_crs:
                        target_plots = target_plots.to_crs(ortho_crs)
                    
                    if args.rotate_real != 0.0:
                        from rasterio.warp import reproject, Resampling
                        from rasterio.transform import Affine
                        
                        # Collective centroid of target plots
                        centroid = target_plots.unary_union.centroid
                        c_x, c_y = centroid.x, centroid.y
                        
                        # Rotate target plots geometries around centroid
                        rotated_plots = target_plots.copy()
                        rotated_plots.geometry = target_plots.geometry.rotate(args.rotate_real, origin=centroid)
                        
                        # Compute bounds of rotated geometries
                        minx, miny, maxx, maxy = rotated_plots.total_bounds
                        
                        # Pixel size from source TIFF
                        px_size = (abs(src.transform.a) + abs(src.transform.e)) / 2
                        
                        # Destination size
                        dst_width = int(np.ceil((maxx - minx) / px_size))
                        dst_height = int(np.ceil((maxy - miny) / px_size))
                        
                        # Destination transform in rotated space
                        dst_transform_rot = Affine.translation(minx, maxy) * Affine.scale(px_size, -px_size)
                        
                        # Compose with inverse rotation back to original CRS
                        rot_to_orig = Affine.translation(c_x, c_y) * Affine.rotation(-args.rotate_real) * Affine.translation(-c_x, -c_y)
                        dst_transform = rot_to_orig * dst_transform_rot
                        
                        # Perform reprojection
                        dst_image = np.zeros((src.count, dst_height, dst_width), dtype=src.dtypes[0])
                        reproject(
                            source=rasterio.band(src, list(range(1, src.count + 1))),
                            destination=dst_image,
                            src_transform=src.transform,
                            src_crs=src.crs,
                            dst_transform=dst_transform,
                            dst_crs=src.crs,
                            resampling=Resampling.bilinear
                        )
                        
                        out_image = np.moveaxis(dst_image[0:3], 0, -1)
                    else:
                        # Compute continuous bounding box encompassing all target plots (unrotated)
                        minx, miny, maxx, maxy = target_plots.total_bounds
                        bbox_shape = [mapping(box(minx, miny, maxx, maxy))]
                        
                        out_image, out_transform = mask(src, bbox_shape, crop=True, filled=False)
                        out_image = np.moveaxis(out_image[0:3], 0, -1) # Convert (C,H,W) to (H,W,C) RGB
                    
                    real_drone_filename = f"merged_{args.end_bed - args.start_bed + 1}x{args.end_tier - args.start_tier + 1}_real_drone_dap{args.dap}.jpeg"
                    real_drone_path = os.path.join(args.output_dir, real_drone_filename)
                    
                    img = Image.fromarray(out_image.astype(np.uint8))
                    img.save(real_drone_path, "JPEG", quality=95)
                    print(f"[SUCCESS] Real drone orthophoto cropped and saved to: {real_drone_path}")
            else:
                print(f"[WARNING] No plots found in GeoJSON matching grid bed {args.start_bed}~{args.end_bed}, tier {args.start_tier}~{args.end_tier}")
        except Exception as e:
            print(f"[WARNING] Failed to crop real drone orthophoto: {e}")

if __name__ == "__main__":
    main()
