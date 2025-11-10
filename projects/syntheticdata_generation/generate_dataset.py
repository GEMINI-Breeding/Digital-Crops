# %%
import os
import shutil
import sys
import subprocess
import json
from pathlib import Path

# %%
# Load example params
params_path = Path("params_rover.json")  # change to the correct filename or absolute path
if not params_path.exists():
    raise FileNotFoundError(f"JSON file not found: {params_path}")

with params_path.open("r", encoding="utf-8") as f:
    params = json.load(f)

print("Loaded params:", params)

# %%
# Load sample images from Agrowstitch result
import shutil
from PIL import Image
import re
from IPython.display import display
from ultralytics import SAM

class AmigaStitchDataset:
    def __init__(
        self,
        root=Path("/home/lion397/GEMINI/heesup/dataset/2025_Davis_Amiga/2025-06-17/Amiga/RGB/AgRowStitch_v0/"),
        program_path = "build_release/main",
        extensions=(".jpg", ".jpeg", ".png", ".tif"),
        transform=None,
        debug=False,
    ):
        self.root = Path(root)
        if not self.root.exists():
            raise FileNotFoundError(f"Root directory not found: {self.root}")
        self.transform = transform

        # filename pattern examples handled:
        # AgRowStitch_plot-12-3.jpg  or  AgRowStitch_plot-12.jpg
        pattern = re.compile(r"AgRowStitch[_-]plot[_-]?(?P<plot>[^-_\.]+)(?:[_-]?(?P<idx>\d+))?", re.IGNORECASE)

        self._files = []
        for p in sorted(self.root.iterdir()):
            if p.is_file() and p.suffix.lower() in extensions:
                m = pattern.search(p.name)
                plot = m.group("plot") if m else None
                idx = int(m.group("idx")) if (m and m.group("idx")) else None
                self._files.append({"path": p, "plot": plot, "idx": idx})

        if not self._files:
            raise RuntimeError(f"No images found in {self.root} matching pattern.")
    
        # Load SAM 2.1 model
        self.SAM_model = SAM("sam2.1_b.pt")

        self.plot_shortest_len = 1.2
        self.img_shape = []

        self.program_path = program_path
        self.debug = debug

    def __len__(self):
        return len(self._files)

    def __getitem__(self, i):
        entry = self._files[i]
        img = Image.open(entry["path"]).convert("RGB")
        if self.transform:
            img = self.transform(img)
        return img, {"path": entry["path"], "plot": entry["plot"], "idx": entry["idx"]}

    def list_plot_ids(self):
        return sorted({e["plot"] for e in self._files if e["plot"] is not None})

    def localize_plants(self, idx=0, exg_thresh=None, min_size=10, show=True, use_sam=True):
        """
        Localize plants using ExG -> 1:1 box centers -> SAM refinement (optional) -> updated bbox.
        
        Args:
            idx: dataset index
            exg_thresh: ExG threshold for binary mask (None for auto Otsu)
            min_size: minimum blob area in pixels
            show: if True, display image with centers and bboxes overlayed
            use_sam: if True, use SAM for refinement; else, use ExG-based centers only
            
        Returns:
            list of dicts with keys: 'center', 'bbox', 'mask'
        """
        import numpy as np
        import cv2
        from skimage import measure
        import matplotlib.pyplot as plt
        import matplotlib.patches as patches
        
        # Step 1: Load image
        entry = self._files[idx]
        img = Image.open(entry["path"]).convert("RGB")
        img_np = np.array(img)
        self.img_shape = img_np.shape
        # Step 2: Compute ExG and binary mask
        r, g, b = img_np[..., 0], img_np[..., 1], img_np[..., 2]
        denom = (r + g + b).astype(np.float32) + 1e-6
        exg = np.clip((2.0 * g - r - b) / denom, -1, 1)
        
        # Apply Gaussian filtering to smooth the ExG image and connect nearby blobs
        exg_blurred = cv2.GaussianBlur(exg.astype(np.float32), (5, 5), 0)
        
        if exg_thresh is None:
            # Auto threshold with Otsu
            exg_norm = ((exg_blurred + 1) * 127.5).astype(np.uint8)
            thresh_val, bin_mask = cv2.threshold(exg_norm, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            exg_thresh = (thresh_val / 127.5) - 1
            if self.debug:
                print(f"Auto threshold (Otsu): {exg_thresh:.3f}")
        else:
            # Manual threshold
            bin_mask = (exg_blurred > exg_thresh).astype(np.uint8) * 255
        
        # Enhanced morphological operations to reduce false positives
        kernel_small = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        kernel_large = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        
        # Remove small noise
        bin_mask = cv2.morphologyEx(bin_mask, cv2.MORPH_OPEN, kernel_small, iterations=2)
        # Close holes
        bin_mask = cv2.morphologyEx(bin_mask, cv2.MORPH_CLOSE, kernel_large, iterations=2)
        # Final smoothing
        bin_mask = cv2.morphologyEx(bin_mask, cv2.MORPH_OPEN, kernel_small)

        # Remove small components with stricter area filter
        labels = measure.label(bin_mask, connectivity=2)
        cleaned = np.zeros_like(bin_mask)
        for prop in measure.regionprops(labels):
            y1, x1, y2, x2 = prop.bbox
            h, w = y2 - y1, x2 - x1
            if max(h,w) >= min_size:
                coords = prop.coords
                cleaned[coords[:, 0], coords[:, 1]] = 255
        
        # Step 3: Split blobs into 1:1 boxes and extract centers
        labeled = measure.label(cleaned, connectivity=2)
        props = measure.regionprops(labeled)
        
        all_centers = []
        blob_info = []  # track which centers belong to which blob
        all_segmented_bboxes = []
        
        for prop in props:
            y1, x1, y2, x2 = prop.bbox
            h, w = y2 - y1, x2 - x1
            
            if w >= h:
                side = h
                n = int(np.ceil(w / side))
                seg_w = w//n
                for i in range(n):
                    seg_x1 = x1 + i * seg_w
                    seg_x2 = min(x1 + (i + 1) * seg_w, x2)
                    seg_y1 = y1
                    seg_y2 = y2
                    all_segmented_bboxes.append((seg_x1, seg_y1, seg_x2, seg_y2))
                    if 0:
                        cx = x1 + (i + 0.5) * w / n
                    else:
                        cx = (seg_x1 + seg_x2) / 2
                    cy = (y1 + y2) / 2.0
                    all_centers.append([cx, cy])
                    blob_info.append(prop.label)
        if self.debug:
            print("All centers:", all_centers)
            print("Blob info:", blob_info)
            
        if len(all_centers) == 0:
            print("No plant centers detected.")
            return []
        
        # Step 4: Refine with SAM or use ExG-based
        if use_sam:
            points = all_centers
            labels = [1] * len(points)  # all foreground points
            
            results = self.SAM_model(str(entry["path"]), points=points, labels=labels)
            
            # Step 5: Extract masks and update bboxes
            refined_plants = []
            
            for i, result in enumerate(results):
                if result.masks is None:
                    continue
                
                # Ultralytics returns masks in result.masks.data (tensor)
                for mask_tensor in result.masks.data:
                    mask = mask_tensor.cpu().numpy().astype(bool)
                    
                    # Update bbox from mask
                    ys, xs = np.where(mask)
                    if ys.size == 0:
                        continue
                        
                    bbox = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))  # x1, y1, x2, y2
                    center = [(bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0]
                    
                    refined_plants.append({
                        'center': center,
                        'bbox': bbox,
                        'mask': mask
                    })
        else:
            # Use ExG-based centers
            refined_plants = []
            # Use ExG-based centers
            refined_plants = []
            for i in range(len(all_centers)):
                seg_bbox = all_segmented_bboxes[i]
                prop_label = blob_info[i]
                full_mask = (labeled == prop_label).astype(bool)
                seg_x1, seg_y1, seg_x2, seg_y2 = seg_bbox
                
                # Extract only the selected region mask
                seg_mask = full_mask[seg_y1:seg_y2, seg_x1:seg_x2]
                
                # Get coordinates of mask pixels in the selected region
                ys, xs = np.where(seg_mask)
                
                if ys.size > 0:
                    # Calculate geometric mean (centroid) in original image coordinates
                    center = [np.mean(xs) + seg_x1, np.mean(ys) + seg_y1]
                    
                    # Calculate bbox based on the selected region mask in original coordinates
                    x1_adj = xs.min() + seg_x1
                    y1_adj = ys.min() + seg_y1
                    x2_adj = xs.max() + seg_x1
                    y2_adj = ys.max() + seg_y1
                    bbox = (x1_adj, y1_adj, x2_adj, y2_adj)
                    
                    # Create full-size mask with only selected region
                    mask_full = np.zeros_like(img_np[:, :, 0], dtype=bool)
                    mask_full[seg_y1:seg_y2, seg_x1:seg_x2] = seg_mask
                else:
                    # Fallback if no mask pixels found
                    center = [(seg_x1 + seg_x2) / 2.0, (seg_y1 + seg_y2) / 2.0]
                    bbox = seg_bbox
                    mask_full = np.zeros_like(img_np[:, :, 0], dtype=bool)
                
                refined_plants.append({
                    'center': center,
                    'bbox': bbox,
                    'mask': mask_full
                })
        
        # Convert to local coordinates (m)
        factor = self.plot_shortest_len / self.img_shape[0]
        for i in range(len(refined_plants)):
            center_scaled_x = (refined_plants[i]['center'][1] - self.img_shape[0]/2) * factor
            center_scaled_y = (refined_plants[i]['center'][0] - self.img_shape[1]/2) * factor
            refined_plants[i]['center_m'] = [center_scaled_x, center_scaled_y]


        # Step 6: Visualize if requested
        if show:
            fig, ax = plt.subplots(3, 1, figsize=(12, 12))
            # Top: ExG binary mask
            im1 = ax[0].imshow(exg)
            # cbar1 = fig.colorbar(im1, ax=ax[0])
            # cbar1.set_label('Color Scale for Subplot 1')
            

            # Top: ExG binary mask
            ax[1].imshow(cleaned, cmap='gray')
            ax[1].axis('off')
            ax[1].set_title(f'ExG Binary Mask (thresh={exg_thresh}, min_size={min_size})', fontsize=12)
            
            # Bottom: Detected plants with centers and bboxes
            ax[2].imshow(img_np)
            ax[2].axis('off')
            
            # # Overlay masks (SAM or ExG-based)
            # for plant in refined_plants:
            #     mask = plant['mask']
            #     ax[2].imshow(mask, alpha=0.3, cmap='Reds')  # Overlay mask with transparency
            
            # Draw all_centers (initial centers from ExG blobs)
            for cx, cy in all_centers:
                ax[2].plot(cx, cy, 'bo', markersize=8, markerfacecolor='none', markeredgewidth=2, label='Initial Centers' if all_centers.index([cx, cy]) == 0 else "")
            

            # Draw centers
            for plant in refined_plants:
                cx, cy = plant['center']
                ax[2].plot(cx, cy, 'r+', markersize=10, markeredgewidth=2, label='Refined Centers' if refined_plants.index(plant) == 0 else "")
            
            # Draw bboxes
            for plant in refined_plants:
                x1, y1, x2, y2 = plant['bbox']
                rect = patches.Rectangle(
                    (x1, y1), x2 - x1, y2 - y1,
                    linewidth=2, edgecolor='yellow', facecolor='none'
                )
                ax[2].add_patch(rect)
            if use_sam:
                ax[2].set_title(f'Detected {len(refined_plants)} plants - {entry["path"].name} (SAM: {use_sam})', fontsize=12)
            else:
                ax[2].set_title(f'Detected {len(refined_plants)} plants - {entry["path"].name}', fontsize=12)
            ax[2].legend()
            plt.tight_layout()
            plt.show()
        
        return refined_plants
    
    def generate_params(self, idx, refined_plants, params, crop_type="cowpea", 
                    bed=0, row=0, age=30):
        # Update json param
        crops = []
        for refined_plant in refined_plants:
            crop = {}
            crop['crop_type'] = crop_type
            crop['bed'] = bed
            crop['row'] = row
            crop['x'] = refined_plant['center_m'][0]
            crop['y'] = refined_plant['center_m'][1]

            crops.append(crop)

        params['plots']['mode'] = 'manual'
        params['plots']['location'] = 'helios'
        params['plots']['year'] = 2025
        params['plots']['crops'] = crops
        params['plantarchitecture']['initialize']['plant_age']['min'] = age
        params['plantarchitecture']['initialize']['plant_age']['max'] = age

        # Update ground size1
        factor = self.plot_shortest_len / self.img_shape[0]
        params['ground']['size_y']['value'] = self.img_shape[1] * factor
        params['ground']['size_x']['value'] = self.img_shape[1] * factor / 1920 * 1080
        params['ground']['use_obj_ground'] = False
        
        # To cover the entir field
        if 0:
            simulated_camera_height = params['ground']['size_x']['value'] / 2
            params['cameraproperties']['camera_height']['min'] = simulated_camera_height
            params['cameraproperties']['camera_height']['max'] = simulated_camera_height
            params['cameraproperties']["camera_resolution_x"]["value"] = self.img_shape[1]
            params['cameraproperties']["camera_resolution_y"]["value"] = self.img_shape[0]
        params['cameraproperties']["camera_positioning"]["center_plants"] = False

        # Save updated params
        # Specify the output file path (adjust as needed)
        entry = self._files[idx]
        output_path = entry["path"].with_suffix('.json')

        # Save the updated params to JSON file
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(params, f, indent=4)

        if self.debug:
            print(f"Updated params saved to {output_path}")

        return output_path

    def run_helios(self, params_path, output_path=None):
        # Generate image 
        # Construct the command
        if output_path is None:
            output_path = "output"
        output_name = str(params_path).split("/")[-1].split(".")[0]
        command = ""
        command += f"cd {self.program_path} && ./main " 
        # command += f"-h 1.0 -o {output_path} -seed {seed} -name {image_name} --xml -tile none -g"
        command += f"-h 1.0 -o {output_path} -n {output_name} -p {params_path} --xml"
        result = subprocess.run(command, shell=True, capture_output=True, text=True)


        # Check if the command was successful
        if result.returncode == 0:
            if self.debug:
                print("Command executed successfully")
                print(result.stdout)  # Print the standard output
            pass
        else:
            if self.debug:
                print(result.stdout)  # Print the standard output
                print(result.stderr)  # Print the error output
                # raise("Command failed")
            pass

from datetime import datetime
# Define the dates
dop = datetime(2025, 5, 27)
dap = datetime(2025, 6, 17) - dop



dataset_path = Path("/home/lion397/GEMINI/heesup/dataset/2025_Davis_Amiga/2025-06-17/Amiga/RGB/AgRowStitch_v0/")
helios_output_path = dataset_path / "helios_result"
# Create the directory if it doesn't exist
helios_output_path.mkdir(parents=True, exist_ok=True)


# %%
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm.auto import tqdm
import copy
import threading
from multiprocessing import Pool
from functools import partial
from tqdm.auto import tqdm
import copy

# Define the dates
dop = datetime(2025, 5, 27)
dap = datetime(2025, 6, 17) - dop

dataset_path = Path("/home/lion397/GEMINI/heesup/dataset/2025_Davis_Amiga/2025-06-17/Amiga/RGB/AgRowStitch_v0/")
helios_output_path = dataset_path / f"helios_result_dap_{dap.days}"
helios_output_path.mkdir(parents=True, exist_ok=True)

# Create dataset to get length
ds = AmigaStitchDataset(
    root=dataset_path,
    program_path="build_release",
    debug=False)
print("Found", len(ds), "images. plot ids:", ds.list_plot_ids())

def process_single_image(idx, dataset_path, helios_output_path, params, dap_days):
    """Process a single image - runs in separate process"""
    try:
        import traceback
        import copy
        
        # Create dataset instance in each process
        ds = AmigaStitchDataset(
            root=dataset_path,
            program_path="build_release",
            debug=False)
        
        img, meta = ds[idx]
        
        plants = ds.localize_plants(idx=idx, min_size=200, use_sam=False, show=False)
        
        if len(plants) == 0:
            return (idx, 0, "No plants detected")
        
        # Update params (use copy to avoid shared state issues)
        generated_param_path = ds.generate_params(idx, plants, copy.deepcopy(params), age=dap_days)
        
        # Run simulation on the output param
        ds.run_helios(generated_param_path, helios_output_path)
        
        return (idx, len(plants), None)
        
    except Exception as e:
        import traceback
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        return (idx, 0, error_msg)

# Parallel execution with Pool
num_workers = 1

# Create partial function with fixed arguments
process_func = partial(
    process_single_image,
    dataset_path=dataset_path,
    helios_output_path=helios_output_path,
    params=params,
    dap_days=dap.days
)

# Process in parallel with progress bar
with Pool(processes=num_workers) as pool:
    results = list(tqdm(
        pool.imap(process_func, range(len(ds))),
        total=len(ds),
        desc="Processing images"
    ))

# Sort results by index for cleaner output
results.sort(key=lambda x: x[0])

# Print summary
print("\n" + "="*60)
successful = sum(1 for _, num_plants, error in results if error is None)
failed = sum(1 for _, num_plants, error in results if error is not None)
total_plants = sum(num_plants for _, num_plants, _ in results)

print(f"Processing complete:")
print(f"  Successful: {successful}/{len(results)}")
print(f"  Failed: {failed}/{len(results)}")
print(f"  Total plants detected: {total_plants}")

# Print detailed errors if any
if failed > 0:
    print("\nDetailed Errors:")
    for idx, _, error in results:
        if error is not None:
            print(f"\n--- Image {idx} ---")
            print(error)
