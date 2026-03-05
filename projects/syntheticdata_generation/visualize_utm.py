"""
visualize_utm.py
────────────────
Plot boundary (WGS-84 GeoJSON) 와 Drone Orthophoto 를
UTM 좌표계로 변환하여 시각화합니다.

실행:
    python visualize_utm.py
"""

import os
import glob
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from pathlib import Path
from PIL import Image
from tqdm import tqdm

import rasterio
import geopandas as gpd
from pyproj import Transformer

# ── 경로 설정 ──────────────────────────────────────────────────────────────
ortho_path       = "/home/lion397/GEMINI/heesup/dataset/2025_Davis/real_data/2025-06-06/Drone/2025-06-06-RGB.tif"
geojson_path     = "/home/lion397/GEMINI/heesup/dataset/2025_Davis/Plot-Boundary-WGS84.geojson"
helios_output_dir= "/home/lion397/GEMINI/heesup/dataset/2025_Davis/HELIOS_20260215/"
dap              = 10
output_dir       = Path(__file__).parent
# ──────────────────────────────────────────────────────────────────────────


def latlon_bounds_to_utm(left, right, bottom, top, src_crs, dst_crs):
    """4-corner 변환으로 WGS-84 bounding box → UTM bounding box."""
    t = Transformer.from_crs(src_crs, dst_crs, always_xy=True)
    ul = t.transform(left,  top)
    ur = t.transform(right, top)
    ll = t.transform(left,  bottom)
    lr = t.transform(right, bottom)
    return (
        min(ul[0], ll[0]),   # utm_left
        max(ur[0], lr[0]),   # utm_right
        min(ll[1], lr[1]),   # utm_bottom
        max(ul[1], ur[1]),   # utm_top
    )


# ── 1. GeoJSON 로드 ────────────────────────────────────────────────────────
print("Loading GeoJSON …")
gdf = gpd.read_file(geojson_path)
print(f"  {len(gdf)} plots, original CRS: {gdf.crs}")

# ── 2. Ortho 로드 (다운샘플) ───────────────────────────────────────────────
print("Loading orthophoto …")
with rasterio.open(ortho_path) as src:
    ortho_crs  = src.crs
    ob         = src.bounds           # original (lat/lon) bounds
    ortho_overview = src.read(
        [1, 2, 3],
        out_shape=(3, src.height // 10, src.width // 10)
    )
    ortho_overview = np.moveaxis(ortho_overview, 0, -1)

print(f"  Ortho CRS : {ortho_crs}")
print(f"  Ortho bounds (WGS-84): {ob}")

# ── 3. UTM zone 자동 결정 ──────────────────────────────────────────────────
lon_c    = (ob.left + ob.right)  / 2
lat_c    = (ob.bottom + ob.top)  / 2
utm_zone = int((lon_c + 180) / 6) + 1
utm_crs  = f"EPSG:{32600 + utm_zone if lat_c >= 0 else 32700 + utm_zone}"
print(f"\nUTM zone: {utm_zone}  →  {utm_crs}")

# ── 4. 좌표 변환 ───────────────────────────────────────────────────────────
# GeoDataFrame → UTM
if str(gdf.crs) != ortho_crs.to_string():
    gdf = gdf.to_crs(str(ortho_crs))
gdf_utm = gdf.to_crs(utm_crs)

# Ortho bounding box → UTM
utm_left, utm_right, utm_bottom, utm_top = latlon_bounds_to_utm(
    ob.left, ob.right, ob.bottom, ob.top,
    str(ortho_crs), utm_crs
)
print(f"Ortho UTM extent:")
print(f"  Easting : {utm_left:.1f} – {utm_right:.1f} m  (Δ={utm_right-utm_left:.1f} m)")
print(f"  Northing: {utm_bottom:.1f} – {utm_top:.1f} m  (Δ={utm_top-utm_bottom:.1f} m)")

plots_bounds_utm = gdf_utm.total_bounds   # [minx, miny, maxx, maxy]
print(f"Plots UTM bounds: {plots_bounds_utm}")

# ── 5. Helios 이미지 목록 ─────────────────────────────────────────────────
dap_images = sorted(glob.glob(os.path.join(helios_output_dir, f"dap_{dap}_plot_*_0000.jpeg")))
print(f"\nFound {len(dap_images)} Helios images for DAP {dap}")

# ── 6. Helios 이미지 → ortho 픽셀 합성 ───────────────────────────────────
ortho_h, ortho_w = ortho_overview.shape[:2]
ext_w = utm_right  - utm_left
ext_h = utm_top    - utm_bottom
px_per_m_x = ortho_w / ext_w
px_per_m_y = ortho_h / ext_h

ortho_with_helios = ortho_overview.copy()

if dap_images:
    print("Compositing Helios images …")
    for img_path in tqdm(dap_images):
        base  = os.path.basename(img_path)
        parts = base.replace('.jpeg', '').split('_')
        col, row = int(parts[3]), int(parts[4])

        plot_gdf = gdf_utm[(gdf_utm['column'] == col) & (gdf_utm['row'] == row)]
        if len(plot_gdf) == 0:
            continue

        pb = plot_gdf.total_bounds           # UTM [minx, miny, maxx, maxy]

        px_minx = int((pb[0] - utm_left)  * px_per_m_x)
        px_maxx = int((pb[2] - utm_left)  * px_per_m_x)
        px_miny = int((utm_top - pb[3])   * px_per_m_y)   # flip Y
        px_maxy = int((utm_top - pb[1])   * px_per_m_y)   # flip Y

        px_minx = max(0, min(px_minx, ortho_w))
        px_maxx = max(0, min(px_maxx, ortho_w))
        px_miny = max(0, min(px_miny, ortho_h))
        px_maxy = max(0, min(px_maxy, ortho_h))

        tw, th = px_maxx - px_minx, px_maxy - px_miny
        if tw > 0 and th > 0:
            hi = np.array(Image.open(img_path).resize((tw, th), Image.LANCZOS))
            if hi.ndim == 2:
                hi = np.stack([hi]*3, axis=-1)
            ortho_with_helios[px_miny:px_maxy, px_minx:px_maxx] = hi[:, :, :3]

# ── 7. 시각화 ─────────────────────────────────────────────────────────────
print("\nRendering figure …")
fig, axes = plt.subplots(1, 2, figsize=(24, 12))
fig.suptitle(
    f'Dataset Overview - DAP {dap}  [UTM Zone {utm_zone}N, {utm_crs}]',
    fontsize=16, fontweight='bold'
)

extent_utm = [utm_left, utm_right, utm_bottom, utm_top]

# Panel 1 ──────────────────────────────────────────────────────────────────
ax1 = axes[0]
ax1.imshow(ortho_overview, extent=extent_utm, aspect='auto')
ax1.set_xlim(plots_bounds_utm[0], plots_bounds_utm[2])
ax1.set_ylim(plots_bounds_utm[1], plots_bounds_utm[3])
gdf_utm.boundary.plot(ax=ax1, color='yellow', linewidth=1, alpha=0.8)
ax1.set_title(f'1. Original Drone Orthophoto\nAll {len(gdf_utm)} Plots', fontsize=14, fontweight='bold')
ax1.set_xlabel(f'Easting (m)  [{utm_crs}]', fontsize=11)
ax1.set_ylabel('Northing (m)', fontsize=11)
ax1.xaxis.set_major_formatter(mticker.FormatStrFormatter('%.0f'))
ax1.yaxis.set_major_formatter(mticker.FormatStrFormatter('%.0f'))
ax1.grid(True, alpha=0.3)

# Panel 2 ──────────────────────────────────────────────────────────────────
ax2 = axes[1]
ax2.imshow(ortho_with_helios, extent=extent_utm, aspect='auto')
ax2.set_xlim(plots_bounds_utm[0], plots_bounds_utm[2])
ax2.set_ylim(plots_bounds_utm[1], plots_bounds_utm[3])
ax2.set_title(
    f'2. Helios Replacement Overlay\nHelios images replacing plot regions (DAP {dap})',
    fontsize=14, fontweight='bold'
)
ax2.set_xlabel(f'Easting (m)  [{utm_crs}]', fontsize=11)
ax2.set_ylabel('Northing (m)', fontsize=11)
ax2.xaxis.set_major_formatter(mticker.FormatStrFormatter('%.0f'))
ax2.yaxis.set_major_formatter(mticker.FormatStrFormatter('%.0f'))
ax2.grid(True, alpha=0.3)

plt.tight_layout()

# ── 저장 ──────────────────────────────────────────────────────────────────
out_path = output_dir / f"dataset_overview_UTM_dap{dap}.png"
plt.savefig(out_path, dpi=150, bbox_inches='tight')
print(f"\n✓ Saved → {out_path}")
plt.show()

# ── 8. Paper Figure: Synthetic vs Real Data ────────────────────────────────
print("\n" + "="*60)
print("Generating Paper Figure: Synthetic vs Real Data in UTM")
print("="*60)

daps_to_visualize = [10, 30, 50, 70, 90]
from datetime import datetime
planting_dt = datetime.strptime("2025-05-27", "%Y-%m-%d")
ortho_data_dir = "/home/lion397/farm_codes/Image2PlantArchitecture_v2/data/raw/2025_Davis/real_data/daps"

ortho_files = sorted(glob.glob(os.path.join(ortho_data_dir, "*.tif")))
print(f"Found {len(ortho_files)} orthophoto files for temporal comparison")

# Function to generate the figure 
def generate_temporal_figure(gdf_filtered, output_filename, title_suffix=""):
    fig = plt.figure(figsize=(18, 12))
    gs = fig.add_gridspec(2, 5, hspace=0.3, left=0.080, right=0.95, top=0.90, bottom=0.05)
    
    current_extent_utm = gdf_filtered.total_bounds  # [minx, miny, maxx, maxy] in UTM
    
    # --- BOTTOM ROWS: Real orthophoto data ---
    print(f"\nProcessing real orthophoto data for {output_filename} ...")
    for idx, ortho_file in enumerate(ortho_files):
        if idx >= 5: break
        
        ax = fig.add_subplot(gs[0, idx])  # Top row
        fn = os.path.basename(ortho_file)
        date_str_raw = fn.split("-RGB")[0]
        dt_obj = datetime.strptime(date_str_raw[:10], "%Y-%m-%d")
        dap_val = (dt_obj - planting_dt).days
        
        with rasterio.open(ortho_file) as src:
            # Transform UTM bounds back to ortho's CRS (Lat/Lon) to compute pixel offsets
            t_inv = Transformer.from_crs(utm_crs, src.crs, always_xy=True)
            ll_x, ll_y = t_inv.transform(current_extent_utm[0], current_extent_utm[1])
            lr_x, lr_y = t_inv.transform(current_extent_utm[2], current_extent_utm[1])
            ul_x, ul_y = t_inv.transform(current_extent_utm[0], current_extent_utm[3])
            ur_x, ur_y = t_inv.transform(current_extent_utm[2], current_extent_utm[3])
            
            src_min_x = min(ll_x, lr_x, ul_x, ur_x)
            src_max_x = max(ll_x, lr_x, ul_x, ur_x)
            src_min_y = min(ll_y, lr_y, ul_y, ur_y)
            src_max_y = max(ll_y, lr_y, ul_y, ur_y)
            
            col_off = int((src_min_x - src.bounds.left) / src.res[0])
            row_off = int((src.bounds.top - src_max_y) / src.res[1])
            width_px = int((src_max_x - src_min_x) / src.res[0])
            height_px = int((src_max_y - src_min_y) / src.res[1])
            
            from rasterio.windows import Window
            v_col_off = max(0, col_off)
            v_row_off = max(0, row_off)
            v_width = max(1, min(width_px, src.width - v_col_off))
            v_height = max(1, min(height_px, src.height - v_row_off))
            window = Window(v_col_off, v_row_off, v_width, v_height)
            
            ortho_crop = src.read([1, 2, 3], window=window, out_shape=(3, v_height // 5, v_width // 5))
            ortho_crop = np.moveaxis(ortho_crop, 0, -1)
            
        ax.imshow(ortho_crop, extent=[current_extent_utm[0], current_extent_utm[2], current_extent_utm[1], current_extent_utm[3]], aspect="equal")
        ax.set_title(f"DAP {dap_val} ({dt_obj.strftime('%Y-%m-%d')})", fontsize=14, fontweight="bold", pad=10)
        ax.set_xlabel(f'Easting (m)', fontsize=11)
        if idx == 0:
            ax.set_ylabel('Northing (m)', fontsize=11)
        ax.xaxis.set_major_formatter(mticker.FormatStrFormatter('%.0f'))
        ax.yaxis.set_major_formatter(mticker.FormatStrFormatter('%.0f'))
        ax.grid(True, alpha=0.3, linestyle='--', color='white')

    # --- TOP ROWS: Synthetic data ---
    print(f"\nProcessing synthetic data for {output_filename} ...")
    with rasterio.open(ortho_files[0]) as src:
        overview_scale = 10
        ortho_overview_temp = src.read([1, 2, 3], out_shape=(3, src.height // overview_scale, src.width // overview_scale))
        ortho_overview_temp = np.moveaxis(ortho_overview_temp, 0, -1)
        
        # Transform WGS-84 bounds to UTM
        t_fwd = Transformer.from_crs(src.crs, utm_crs, always_xy=True)
        ll_x, ll_y = t_fwd.transform(src.bounds.left, src.bounds.bottom)
        lr_x, lr_y = t_fwd.transform(src.bounds.right, src.bounds.bottom)
        ul_x, ul_y = t_fwd.transform(src.bounds.left, src.bounds.top)
        ur_x, ur_y = t_fwd.transform(src.bounds.right, src.bounds.top)
        
        utm_min_x = min(ll_x, lr_x, ul_x, ur_x)
        utm_max_x = max(ll_x, lr_x, ul_x, ur_x)
        utm_min_y = min(ll_y, lr_y, ul_y, ur_y)
        utm_max_y = max(ll_y, lr_y, ul_y, ur_y)
        
    ortho_height_temp, ortho_width_temp = ortho_overview_temp.shape[:2]
    ortho_extent_width_temp = utm_max_x - utm_min_x
    ortho_extent_height_temp = utm_max_y - utm_min_y
    px_per_meter_x_temp = ortho_width_temp / ortho_extent_width_temp
    px_per_meter_y_temp = ortho_height_temp / ortho_extent_height_temp

    for idx, d_val in enumerate(daps_to_visualize):
        if idx >= 5: break
        
        ax = fig.add_subplot(gs[1, idx])  # Bottom row
        
        helios_images = glob.glob(os.path.join(helios_output_dir, f"dap_{d_val}_plot_*_0000.jpeg"))
        
        if len(helios_images) == 0:
            ax.text(0.5, 0.5, f"No data for DAP {d_val}", ha="center", va="center")
            ax.axis("off")
            continue
            
        synthetic_canvas = np.zeros_like(ortho_overview_temp)
        synthetic_canvas[:, :, 0] = 119  
        synthetic_canvas[:, :, 1] = 115   
        synthetic_canvas[:, :, 2] = 102   
        
        for img_path in helios_images:
            basename = os.path.basename(img_path)
            parts = basename.replace(".jpeg", "").split("_")
            col, row = int(parts[3]), int(parts[4])
            
            plot_gdf_temp = gdf_filtered[(gdf_filtered["column"] == col) & (gdf_filtered["row"] == row)]
            if len(plot_gdf_temp) > 0:
                plot_bounds_temp = plot_gdf_temp.total_bounds
                px_minx = int((plot_bounds_temp[0] - utm_min_x) * px_per_meter_x_temp)
                px_maxx = int((plot_bounds_temp[2] - utm_min_x) * px_per_meter_x_temp)
                px_miny = int((utm_max_y - plot_bounds_temp[3]) * px_per_meter_y_temp)
                px_maxy = int((utm_max_y - plot_bounds_temp[1]) * px_per_meter_y_temp)
                
                px_minx, px_maxx = max(0, px_minx), min(px_maxx, ortho_width_temp)
                px_miny, px_maxy = max(0, px_miny), min(px_maxy, ortho_height_temp)
                
                tw, th = px_maxx - px_minx, px_maxy - px_miny
                if tw > 0 and th > 0:
                    h_img = Image.open(img_path).resize((tw, th), Image.LANCZOS)
                    synthetic_canvas[px_miny:px_maxy, px_minx:px_maxx] = np.array(h_img)
                    
        ax.imshow(synthetic_canvas, extent=[utm_min_x, utm_max_x, utm_min_y, utm_max_y], aspect="equal")
        ax.set_xlim(current_extent_utm[0], current_extent_utm[2])
        ax.set_ylim(current_extent_utm[1], current_extent_utm[3])
        
        ax.set_title(f"DAP {d_val}", fontsize=14, fontweight="bold", pad=10)
        ax.set_xlabel(f'Easting (m)', fontsize=11)
        if idx == 0:
            ax.set_ylabel('Northing (m)', fontsize=11)
        ax.xaxis.set_major_formatter(mticker.FormatStrFormatter('%.0f'))
        ax.yaxis.set_major_formatter(mticker.FormatStrFormatter('%.0f'))
        ax.grid(True, alpha=0.3, linestyle='--', color='white')

    fig.text(0.04, 0.73, "(a) Real Orthophoto", fontsize=18, fontweight="bold", rotation=90, va="center", ha="center")
    fig.text(0.04, 0.28, "(b) Synthetic Data", fontsize=18, fontweight="bold", rotation=90, va="center", ha="center")
    
    fig.suptitle(f'Temporal Comparison: Synthetic vs Real Data {title_suffix}\n[{utm_crs}]', fontsize=20, fontweight='bold', y=0.98)
    
    out_path = output_dir / output_filename
    plt.savefig(out_path, dpi=200, bbox_inches="tight")
    print(f"✓ Saved Figure → {out_path}")
    plt.close((fig))

# Generate unfiltered version (All beds)
generate_temporal_figure(gdf_utm, "paper_figure_synthetic_vs_real_UTM.png", "(All Plots)")

# Generate filtered version (Beds 1-16)
gdf_filtered = gdf_utm[(gdf_utm["column"] >= 1) & (gdf_utm["column"] <= 16)]
generate_temporal_figure(gdf_filtered, "paper_figure_synthetic_vs_real_bed1-16_UTM.png", "(Beds 1-16)")

