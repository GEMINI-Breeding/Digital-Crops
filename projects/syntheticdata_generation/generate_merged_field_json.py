import os
import json
import glob
import subprocess
import numpy as np

def generate_merged_json(dap=10, start_bed=1, end_bed=2, 
                        start_tier=1, end_tier=2, method="Method4_+FewshotImages", sim_mode="radiation", output_filename=None,
                        left_to_right_bed=True, bottom_to_top_tier=True, write_xml=False,
                        sim_flags=None):
    """
    Generates a merged parameter JSON for a specific subset grid of plots and triggers the C++ simulation engine.
    """
    base_dir = "/home/lion397/codes/Image2PlantArchitecture_v2/notebooks/evaluation_results/2025_Davis_temperature_0/real_fewshot_real_image_rendered/gemma4_31b"
    
    n_beds = end_bed - start_bed + 1
    n_tiers = end_tier - start_tier + 1

    if output_filename is None:
        output_filename = f"merged_dap{dap}_bed{start_bed}to{end_bed}_tier{start_tier}to{end_tier}_{sim_mode}_params.json"

    search_pattern = os.path.join(base_dir, f"dap_{dap}_plot_*_*_0000_{method}_0000_params.json")
    json_files = glob.glob(search_pattern)
    
    if not json_files:
        print(f"Cannot find specific method files for '{method}', falling back to general params pattern...")
        json_files = glob.glob(os.path.join(base_dir, f"dap_{dap}_plot_*_*_0000_params.json"))

    if not json_files:
        print(f"Cannot find DAP {dap} parameter JSON files in: {base_dir}")
        return

    # 1. Filter plots within target grid and deduplicate by (bed, tier)
    plots_dict = {}
    plot_size_xs, plot_size_ys, plot_size_zs = [], [], []
    sun_elevs, sun_azis = [], []
    chlorophylls = []

    for f_path in json_files:
        basename = os.path.basename(f_path)
        parts = basename.split("_")
        bed_idx = int(parts[3])
        tier_idx = int(parts[4])

        if start_bed <= bed_idx <= end_bed and start_tier <= tier_idx <= end_tier:
            if (bed_idx, tier_idx) not in plots_dict:
                with open(f_path, "r") as f:
                    data = json.load(f)
                
                plots_dict[(bed_idx, tier_idx)] = {"bed": bed_idx, "tier": tier_idx, "data": data, "path": f_path}
                
                layout = data.get("field", {}).get("layout", {})
                plot_size_xs.append(layout.get("plot_size_x", 1.35))
                plot_size_ys.append(layout.get("plot_size_y", 3.84))
                plot_size_zs.append(layout.get("plot_size_z", 0.2))

                sun = data.get("environment", {}).get("sun", {})
                sun_elevs.append(sun.get("elevation_degrees", 45.0))
                sun_azis.append(sun.get("azimuth_degrees", 180.0))

                optics = data.get("plant_properties", {}).get("leaf_optics", {})
                chlorophylls.append(optics.get("chlorophyll_content", 30.0))

    if not plots_dict:
        print(f"No plots match the criteria (bed {start_bed}~{end_bed}, tier {start_tier}~{end_tier}).")
        return

    plots_data = list(plots_dict.values())
    plots_data.sort(key=lambda item: (item["bed"], item["tier"]))
    print(f"Merging exactly {len(plots_data)} distinct plots into {n_beds}x{n_tiers} layout...")

    avg_ps_x = float(np.mean(plot_size_xs))
    avg_ps_y = float(np.mean(plot_size_ys))
    avg_ps_z = float(np.mean(plot_size_zs))
    avg_sun_elev = float(np.mean(sun_elevs))
    avg_sun_azi = float(np.mean(sun_azis))
    avg_chlorophyll = float(np.mean(chlorophylls))

    merged_data = json.loads(json.dumps(plots_data[0]["data"]))

    merged_data["environment"]["sun"]["elevation_degrees"] = avg_sun_elev
    merged_data["environment"]["sun"]["azimuth_degrees"] = avg_sun_azi
    merged_data["plant_properties"]["leaf_optics"]["chlorophyll_content"] = avg_chlorophyll

    merged_plots = []
    for item in plots_data:
        bed_idx = item["bed"]
        tier_idx = item["tier"]
        orig_plots = item["data"].get("field", {}).get("plots", [])

        if orig_plots:
            plot = json.loads(json.dumps(orig_plots[0]))
            
            # Assign bed position based on left_to_right_bed direction
            if left_to_right_bed:
                plot["bed"] = bed_idx - start_bed + 1
            else:
                plot["bed"] = n_beds - (bed_idx - start_bed)
            
            # Assign row position based on bottom_to_top_tier direction
            if bottom_to_top_tier:
                plot["row"] = tier_idx - start_tier + 1
            else:
                plot["row"] = n_tiers - (tier_idx - start_tier)
                
            merged_plots.append(plot)

    # 4. Configure field layout
    # CRITICAL FIX: Keep plot_size_x and plot_size_y as single plot dimensions (avg_ps_x, avg_ps_y)
    # so C++ make_field() and manual translation align adjacent plots perfectly without wide gaps.
    field = merged_data.get("field", {})
    field["num_beds"] = n_beds
    field["num_rows"] = n_tiers
    field["plots"] = merged_plots

    if "layout" in field:
        field["layout"]["mode"] = "manual"
        field["layout"]["plot_size_x"] = avg_ps_x
        field["layout"]["plot_size_y"] = avg_ps_y
        field["layout"]["plot_size_z"] = avg_ps_z
        field["layout"]["num_beds"] = n_beds
        field["layout"]["num_rows"] = n_tiers

    if "plot_shape" in field:
        field["plot_shape"]["mode"] = "manual"
        field["plot_shape"]["plot_size_x"] = avg_ps_x
        field["plot_shape"]["plot_size_y"] = avg_ps_y
        field["plot_shape"]["plot_size_z"] = avg_ps_z
        field["plot_shape"]["num_beds"] = n_beds
        field["plot_shape"]["num_rows"] = n_tiers

    # 5. Configure camera positioning and FOV scaling
    # Since init_camera() runs before crops are loaded in C++, focusing_plants yields origin (0,0).
    # We explicitly offset the lookat coordinates to the exact geometric center of the merged field.
    center_x = round(avg_ps_x * (n_beds - 1) / 2.0, 4)
    center_y = round(avg_ps_y * (n_tiers - 1) / 2.0, 4)
    
    camera = merged_data.get("camera", {})
    if "sensor" not in camera: camera["sensor"] = {}
    
    # Calculate aspect-matched vertical resolution to perfectly encompass the rectangular plot grid
    total_x = avg_ps_x * n_beds
    total_y = avg_ps_y * n_tiers
    res_x = 2000
    res_y = int(res_x * (total_y / total_x))
    
    camera["sensor"]["resolution_x"] = res_x
    camera["sensor"]["resolution_y"] = res_y

    # Camera height is fixed at drone altitude (5.0m).
    # C++ engine dynamically recalculates HFOV to encompass the total combined field width.
    if "positioning" not in camera: camera["positioning"] = {}
    camera["positioning"]["camera_height"] = 5.0
    camera["positioning"]["focusing_plants"] = False # Disable auto-focus to rely on C++ native geometric center
    camera["positioning"]["lookat_offset_x"] = 0.0
    camera["positioning"]["lookat_offset_y"] = 0.0
    camera["positioning"]["lookat_offset_z"] = 0.0

    out_path = os.path.join(os.getcwd(), output_filename)
    with open(out_path, "w") as f:
        json.dump(merged_data, f, indent=4)
    
    print(f"Merged JSON file generated successfully: {out_path}")
    print(f" -> Total {len(merged_plots)} distinct plots merged into {n_beds}x{n_tiers} layout.")

    # 6. Execute C++ Renderer
    binary_path = "./main"
    build_dir = os.path.join(os.getcwd(), "build_release")
    output_dir = os.path.join(os.getcwd(), "test_merged_output")
    output_name = f"merged_dap{dap}_bed{start_bed}to{end_bed}_tier{start_tier}to{end_tier}_{sim_mode}"

    print(f"\n==================================================")
    print(f"Launching C++ Simulation Engine ({sim_mode.upper()} MODE)")
    print(f"==================================================")
    
    cmd = [
        binary_path,
        "-f", out_path,
        "-o", output_dir,
        "-n", output_name,
    ]

    if sim_mode == "vis":
        cmd.extend(["--renderer", "vis"])
    else:
        cmd.extend(["--renderer", "radiation"])

    if not write_xml:
        cmd.extend(["--no-save-xml"])

        
    if sim_flags is None:
        sim_flags = {"multispectral": False, "temperature": True, "depth": True, "wue": False}

    if sim_flags.get("multispectral", False):
        cmd.extend(["--multispectral", "true"])
    else:
        cmd.extend(["--multispectral", "false"])
        
    if sim_flags.get("temperature", False):
        cmd.extend(["--temperature", "true"])
    else:
        cmd.extend(["--temperature", "false"])
        
    if sim_flags.get("depth", False):
        cmd.extend(["--depth", "true"])
    else:
        cmd.extend(["--depth", "false"])


    
    exec_env = os.environ.copy()
    exec_env["DISPLAY"] = ":2.0"

    try:
        result = subprocess.run(cmd, cwd=build_dir, env=exec_env, check=True)
        print(f"\n[SUCCESS] Simulation completed. Rendered outputs saved in: {output_dir}")
        
        # Apply colormaps to output depth and temperature images
        import cv2

        try:
            depth_path = os.path.join(output_dir, f"{output_name}_0000_depth.jpeg")
            if os.path.exists(depth_path):
                # Read grayscale depth and isolate plant height range for contrast maximization
                depth_img = cv2.imread(depth_path, cv2.IMREAD_GRAYSCALE)
                if depth_img is not None:
                    # Ground is at ~5.0m distance (high pixel values close to 230-240)
                    # Plants are closer (lower pixel values ~180-210)
                    # We segment ground vs crop, stretch crop depth to 0-220 range, and set ground to 255
                    mask_bg = (depth_img > 220)
                    mask_crop = ~mask_bg
                    
                    out_depth = np.zeros_like(depth_img, dtype=np.uint8)
                    out_depth[mask_bg] = 255 # Ground background farthest distance (Magenta in COOL)
                    
                    if np.any(mask_crop):
                        crop_vals = depth_img[mask_crop]
                        c_min, c_max = float(crop_vals.min()), float(crop_vals.max())
                        if c_max > c_min:
                            # Stretch crop height range across 0 to 220
                            out_depth[mask_crop] = np.clip(((crop_vals - c_min) / (c_max - c_min)) * 220, 0, 220).astype(np.uint8)
                        else:
                            out_depth[mask_crop] = 100
                    
                    depth_colorized = cv2.applyColorMap(out_depth, cv2.COLORMAP_JET)
                    cv2.imwrite(os.path.join(output_dir, f"{output_name}_0000_depth_jet.jpeg"), depth_colorized)
                    print(f"[SUCCESS] Applied plant-height-stretched COOL colormap to Depth image: {output_name}_0000_depth_cool.jpeg")

            lw_path = os.path.join(output_dir, f"{output_name}_0000_temperature.jpeg")
            if os.path.exists(lw_path):
                lw_img = cv2.imread(lw_path, cv2.IMREAD_GRAYSCALE)
                if lw_img is not None:
                    temp_inferno = cv2.applyColorMap(lw_img, cv2.COLORMAP_INFERNO)
                    cv2.imwrite(os.path.join(output_dir, f"{output_name}_0000_temperature_inferno.jpeg"), temp_inferno)
                    print(f"[SUCCESS] Applied pure INFERNO colormap to Temperature image: {output_name}_0000_temperature.jpeg")


        except Exception as e:
            print(f"[WARNING] Failed to apply colormaps: {e}")
        
        # 7. Crop Real Drone Orthophoto matching the plot grid envelope
        dap_to_tif = {
            10: "/home/lion397/GEMINI/heesup/dataset/2025_Davis/real_data/2025-06-06/Drone/2025-06-06-RGB.tif",
            28: "/home/lion397/GEMINI/heesup/dataset/2025_Davis/real_data/2025-06-24/2025-06-24-Drone-10m-RGB.tif",
            49: "/home/lion397/GEMINI/heesup/dataset/2025_Davis/real_data/2025-07-15/2025-07-15-RGB-10m.tif",
            70: "/home/lion397/GEMINI/heesup/dataset/2025_Davis/real_data/2025-08-05/2025-08-05-10m-RGB.tif",
            87: "/home/lion397/GEMINI/heesup/dataset/2025_Davis/real_data/2025-08-22/2025-08-22-10m-RGB.tif",
        }
        geojson_path = "/home/lion397/GEMINI/heesup/dataset/2025_Davis/Plot-Boundary-WGS84.geojson"
        ortho_path = dap_to_tif.get(dap)
        
        if not ortho_path or not os.path.exists(ortho_path):
            print(f"[WARNING] Ortho TIF not found for DAP {dap}: {ortho_path}")
        elif not os.path.exists(geojson_path):
            print(f"[WARNING] GeoJSON not found: {geojson_path}")
        else:
            print(f"\n==================================================")
            print(f"Cropping Real Drone Orthophoto for DAP {dap}")
            print(f"==================================================")
            import geopandas as gpd
            import rasterio
            from rasterio.mask import mask
            from shapely.geometry import mapping, box
            from PIL import Image
            
            gdf = gpd.read_file(geojson_path)
            # Find plots matching grid (column is bed, row is tier)
            target_plots = gdf[(gdf['column'] >= start_bed) & (gdf['column'] <= end_bed) & 
                               (gdf['row'] >= start_tier) & (gdf['row'] <= end_tier)]
            
            if len(target_plots) > 0:
                # Reproject GeoJSON to match ortho CRS if needed
                with rasterio.open(ortho_path) as src:
                    ortho_crs = src.crs
                    if gdf.crs != ortho_crs:
                        target_plots = target_plots.to_crs(ortho_crs)
                    
                    # Compute continuous bounding box encompassing all target plots
                    minx, miny, maxx, maxy = target_plots.total_bounds
                    bbox_shape = [mapping(box(minx, miny, maxx, maxy))]
                    
                    out_image, out_transform = mask(src, bbox_shape, crop=True, filled=False)
                    out_image = np.moveaxis(out_image[0:3], 0, -1) # Convert (C,H,W) to (H,W,C) RGB
                    
                    real_drone_filename = f"merged_{n_beds}x{n_tiers}_real_drone_dap{dap}.jpeg"
                    real_drone_path = os.path.join(output_dir, real_drone_filename)
                    
                    img = Image.fromarray(out_image.astype(np.uint8))
                    img.save(real_drone_path, "JPEG", quality=95)
                    print(f"[SUCCESS] Real drone orthophoto cropped and saved to: {real_drone_path}")
            else:
                print(f"[WARNING] No plots found in GeoJSON matching grid bed {start_bed}~{end_bed}, tier {start_tier}~{end_tier}")
                
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] Simulation failed with exit code {e.returncode}")

if __name__ == "__main__":
    import argparse

    def str2bool(v):
        if isinstance(v, bool):
            return v
        if v.lower() in ('yes', 'true', 't', 'y', '1'):
            return True
        elif v.lower() in ('no', 'false', 'f', 'n', '0'):
            return False
        else:
            raise argparse.ArgumentTypeError('Boolean value expected.')

    parser = argparse.ArgumentParser(description="Merge field JSON and run simulation engine.")
    parser.add_argument("--dap", type=int, default=28, help="Days After Planting (DAP) value (e.g. 10, 28, 49, 70, 87)")
    parser.add_argument("--start_bed", type=int, default=1, help="Start bed index")
    parser.add_argument("--end_bed", type=int, default=8, help="End bed index")
    parser.add_argument("--start_tier", type=int, default=1, help="Start tier index")
    parser.add_argument("--end_tier", type=int, default=14, help="End tier index")
    parser.add_argument("--method", type=str, default="Method4_+FewshotImages", help="Parameter optimization method")
    parser.add_argument("--sim_mode", type=str, default="radiation", choices=["radiation", "vis"], help="Simulation mode")
    parser.add_argument("--output_filename", type=str, default=None, help="Output JSON filename (optional; auto-generated if omitted)")
    parser.add_argument("--left_to_right_bed", type=str2bool, default=False, help="Bed ordering direction")
    parser.add_argument("--bottom_to_top_tier", type=str2bool, default=True, help="Tier ordering direction")
    parser.add_argument("--write_xml", type=str2bool, default=False, help="Write simulation XML files")
    
    # Sim flags
    parser.add_argument("--multispectral", type=str2bool, default=False, help="Enable multispectral simulation")
    parser.add_argument("--temperature", type=str2bool, default=True, help="Enable temperature simulation")
    parser.add_argument("--depth", type=str2bool, default=True, help="Enable depth simulation")
    parser.add_argument("--wue", type=str2bool, default=False, help="Enable Water Use Efficiency (WUE)")

    args = parser.parse_args()

    sim_flags = {
        "multispectral": args.multispectral,
        "temperature": args.temperature,
        "depth": args.depth,
        "wue": args.wue
    }

    generate_merged_json(
        dap=args.dap,
        start_bed=args.start_bed,
        end_bed=args.end_bed,
        start_tier=args.start_tier,
        end_tier=args.end_tier,
        method=args.method,
        sim_mode=args.sim_mode,
        output_filename=args.output_filename,
        left_to_right_bed=args.left_to_right_bed,
        bottom_to_top_tier=args.bottom_to_top_tier,
        write_xml=args.write_xml,
        sim_flags=sim_flags
    )

