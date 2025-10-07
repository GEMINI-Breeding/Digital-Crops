#!/usr/bin/env python3
"""
Image + Labels + Params Viewer with navigation (Local GUI)

Install:
  pip install matplotlib pillow

Run:
  python viewer.py /path/to/folder

A local GUI window will pop up for browsing images with labels and parameters.
Use arrow keys or buttons to navigate between images.

Data format expected:
  - Images:            0000.jpeg, 0001.jpeg, ...
  - Labels JSON:       0000_labels.json, 0001_labels.json, ...
  - Parameters JSON:   0000_params.json, 0001_params.json, ...
"""
import json
import sys
import textwrap
from pathlib import Path
from typing import Dict, Any, List, Optional

from PIL import Image
import matplotlib.pyplot as plt
from matplotlib.widgets import Button
from matplotlib.patches import Rectangle
from matplotlib.collections import PatchCollection


def natural_sort_key(p: Path):
    """Sorts numerically if basename is zero-padded (e.g., 0001.jpeg)."""
    stem = p.stem
    try:
        return (0, int(stem))
    except ValueError:
        return (1, stem)


def find_images(folder: Path) -> List[Path]:
    imgs = list(folder.glob("*.jpeg")) + list(folder.glob("*.jpg")) + list(folder.glob("*.png"))
    imgs = sorted(imgs, key=natural_sort_key)
    return imgs


def load_json_safely(p: Path) -> Optional[Dict[str, Any]]:
    if not p.exists():
        return None
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] Failed to read {p.name}: {e}")
        return None


def fmt_params(obj: Any, width: int = 48, indent: int = 0) -> str:
    """
    Pretty-format a nested dict/list into wrapped text for the right panel.
    """
    lines = []
    prefix = "  " * indent

    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                lines.append(f"{prefix}{k}:")
                lines.append(fmt_params(v, width=width, indent=indent + 1))
            else:
                val = repr(v)
                wrapped = textwrap.fill(f"{k}: {val}", width=width, subsequent_indent=prefix + "  ")
                lines.append(prefix + wrapped)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, (dict, list)):
                lines.append(f"{prefix}-")
                lines.append(fmt_params(v, width=width, indent=indent + 1))
            else:
                wrapped = textwrap.fill(f"- {repr(v)}", width=width, subsequent_indent=prefix + "  ")
                lines.append(prefix + wrapped)
    else:
        wrapped = textwrap.fill(repr(obj), width=width, subsequent_indent=prefix + "  ")
        lines.append(prefix + wrapped)

    return "\n".join(lines)


def parse_coco_labels(label_json: Dict[str, Any]):
    """
    Returns:
      categories: dict[int->str]
      anns: list of dicts with possible 'bbox' and 'category_id'
      image_id_for_file: (optional) ID we consider matched for single-image files
    """
    categories = {c.get("id"): c.get("name", str(c.get("id"))) for c in label_json.get("categories", [])}
    anns = label_json.get("annotations", []) or []
    images = label_json.get("images", []) or []
    image_id = images[0]["id"] if images and "id" in images[0] else None
    return categories, anns, image_id


class ImageWithLabelsViewer:
    def __init__(self, folder: Path):
        self.folder = folder
        self.images = find_images(folder)
        if not self.images:
            raise SystemExit(f"No images found in {folder}")

        # State
        self.idx = 0

        # Matplotlib layout
        self.fig = plt.figure(figsize=(12, 7), constrained_layout=True)
        gs = self.fig.add_gridspec(nrows=3, ncols=3, height_ratios=[20, 1, 1], width_ratios=[3, 3, 2])

        # Main image axis (large)
        self.ax_img = self.fig.add_subplot(gs[0, 0:2])
        self.ax_img.axis("off")

        # Right text axis
        self.ax_txt = self.fig.add_subplot(gs[0, 2])
        self.ax_txt.axis("off")

        # Buttons
        self.ax_prev = self.fig.add_subplot(gs[1, 0])
        self.ax_prev.axis("off")
        self.btn_prev = Button(self.ax_prev, "← Previous")
        self.btn_prev.on_clicked(self.on_prev)

        self.ax_next = self.fig.add_subplot(gs[1, 1])
        self.ax_next.axis("off")
        self.btn_next = Button(self.ax_next, "Next →")
        self.btn_next.on_clicked(self.on_next)

        # Filename display
        self.ax_info = self.fig.add_subplot(gs[1, 2])
        self.ax_info.axis("off")

        # Legend / categories area (optional)
        self.ax_legend = self.fig.add_subplot(gs[2, 0:3])
        self.ax_legend.axis("off")

        # Keyboard bindings
        self.fig.canvas.mpl_connect("key_press_event", self.on_key)

        # First draw
        self.redraw()

    def on_key(self, event):
        if event.key in ["right", "d", "n"]:
            self.next_image()
        elif event.key in ["left", "a", "p"]:
            self.prev_image()

    def on_prev(self, _event):
        self.prev_image()

    def on_next(self, _event):
        self.next_image()

    def prev_image(self):
        self.idx = (self.idx - 1) % len(self.images)
        self.redraw()

    def next_image(self):
        self.idx = (self.idx + 1) % len(self.images)
        self.redraw()

    def redraw(self):
        img_path = self.images[self.idx]
        stem = img_path.stem  # e.g., "0000"
        label_path = self.folder / f"{stem}_labels.json"
        params_path = self.folder / f"{stem}_params.json"

        # Clear axes
        self.ax_img.cla()
        self.ax_txt.cla()
        self.ax_info.cla()
        self.ax_legend.cla()
        self.ax_img.axis("off")
        self.ax_txt.axis("off")
        self.ax_info.axis("off")
        self.ax_legend.axis("off")

        # Load and display image
        try:
            im = Image.open(img_path).convert("RGB")
            self.ax_img.imshow(im)
            self.ax_img.set_title(img_path.name, fontsize=11)
        except Exception as e:
            self.ax_img.text(0.5, 0.5, f"Failed to open image:\n{e}", ha="center", va="center", fontsize=12)
            im = None

        # Load labels & overlay
        label_json = load_json_safely(label_path)
        categories_map = {}
        anns_for_this = []
        if label_json:
            categories_map, anns, image_id = parse_coco_labels(label_json)
            # If multiple image entries exist, we try to match by filename; fall back to first image_id
            target_image_id = image_id
            try:
                # Try match by file_name
                imgs = label_json.get("images", [])
                for img_rec in imgs:
                    if Path(img_rec.get("file_name", "")).name == img_path.name:
                        target_image_id = img_rec.get("id", target_image_id)
                        break
            except Exception:
                pass

            # Filter annotations for this image_id if present
            if target_image_id is not None:
                anns_for_this = [a for a in anns if a.get("image_id") == target_image_id]
            else:
                # If not provided, assume all anns belong to this single image file
                anns_for_this = anns

        # Draw bboxes if present
        drawn_any_box = False
        patches = []
        colors = []
        cat_names_present = set()

        if im is not None and anns_for_this:
            for ann in anns_for_this:
                cat_id = ann.get("category_id")
                cat_names_present.add(categories_map.get(cat_id, str(cat_id)))
                bbox = ann.get("bbox")
                if bbox and len(bbox) == 4:
                    x, y, w, h = bbox
                    rect = Rectangle((x, y), w, h, fill=False, linewidth=1.5)
                    patches.append(rect)
                    colors.append(None)  # default color
                    # label text
                    self.ax_img.text(
                        x,
                        y - 2,
                        str(cat_id),
                        fontsize=9,
                        color="white",
                        bbox=dict(facecolor="black", alpha=0.5, pad=1),
                        va="bottom",
                    )
                    drawn_any_box = True

            if patches:
                pc = PatchCollection(patches, match_original=True)
                self.ax_img.add_collection(pc)

        # If no boxes, at least show categories we know about
        if label_json and not drawn_any_box:
            # Show category list under the image title
            cat_line = ", ".join(sorted(c for c in cat_names_present if c)) if cat_names_present else \
                       ", ".join(sorted(categories_map.values())) if categories_map else "No categories"
            self.ax_img.set_title(f"{img_path.name}  |  Categories: {cat_line}", fontsize=11)

        # Load params and display on right
        params_json = load_json_safely(params_path)
        if params_json is not None:
            txt = fmt_params(params_json, width=46)
            self.ax_txt.text(0, 1, txt, va="top", ha="left", family="monospace", fontsize=9)
            self.ax_txt.set_title(f"{params_path.name}", fontsize=11)
        else:
            self.ax_txt.text(0.5, 0.5, "No params JSON found", ha="center", va="center", fontsize=10)

        # Info line (index and counts)
        self.ax_info.text(
            0.02, 0.6,
            f"{self.idx + 1}/{len(self.images)}",
            fontsize=11, ha="left", va="center"
        )
        self.ax_info.text(0.02, 0.2, "Tip: use ← / → keys", fontsize=9, ha="left", va="center", alpha=0.7)

        # Legend (category id -> name)
        if categories_map:
            legend_lines = ["Categories:"]
            for cid in sorted(categories_map.keys()):
                legend_lines.append(f"  {cid}: {categories_map[cid]}")
            self.ax_legend.text(0, 0.5, "\n".join(legend_lines), va="center", ha="left", family="monospace", fontsize=9)

        self.fig.canvas.draw_idle()


def main():
    if len(sys.argv) < 2:
        print("Usage: python viewer.py /path/to/folder")
        print("Opens a local GUI window for viewing images with labels and parameters")
        sys.exit(1)

    folder = Path(sys.argv[1]).expanduser().resolve()
    if not folder.exists():
        print(f"Folder not found: {folder}")
        sys.exit(1)

    print(f"Opening local viewer for: {folder}")
    print("Use arrow keys or buttons to navigate between images")
    print("Close the window or press Ctrl+C to exit")

    viewer = ImageWithLabelsViewer(folder)
    plt.show()


if __name__ == "__main__":
    main()
