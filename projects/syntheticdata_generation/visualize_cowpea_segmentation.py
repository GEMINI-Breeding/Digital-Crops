#!/usr/bin/env python3
"""
Visualization script for COCO JSON segmentation masks.
This script displays the generated image alongside the segmentation masks.
"""

import json
import numpy as np
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw, ImageFont
import matplotlib.patches as patches
from matplotlib.patches import Polygon
import argparse
import os

def load_classes(classes_path):
    """Load class names from classes.txt file"""
    classes = {}
    if os.path.exists(classes_path):
        with open(classes_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(maxsplit=1)
                if len(parts) == 2:
                    class_id = int(parts[0])
                    class_name = parts[1]
                    classes[class_id] = class_name
    return classes

def load_txt(txt_path, classes):
    """Load bounding boxes from YOLO format txt file"""
    boxes = []
    with open(txt_path, 'r') as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line: 
                continue
            parts = line.split()
            if len(parts) < 5:
                continue
            cls_id = parts[0]
            x_c, y_c, w, h = map(float, parts[1:5])
            boxes.append((cls_id, x_c, y_c, w, h))
    return boxes

def draw_boxes(image_path, boxes, classes, out_path=None):
    im = Image.open(image_path).convert("RGBA")
    W, H = im.size
    draw = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 14)
    except:
        font = ImageFont.load_default()

    colors = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4"]
    for i, (cls_id, x_c, y_c, w, h) in enumerate(boxes):
        xc = x_c * W
        yc = y_c * H
        bw = w * W
        bh = h * H
        xmin = max(0, xc - bw/2)
        ymin = max(0, yc - bh/2)
        xmax = min(W, xc + bw/2)
        ymax = min(H, yc + bh/2)
        color = colors[int(cls_id) % len(colors)] if cls_id.isdigit() else "#FFFFFF"
        draw.rectangle([xmin, ymin, xmax, ymax], outline=color, width=3)
        
        # Get class name if available
        class_name = classes.get(int(cls_id), cls_id) if cls_id.isdigit() else cls_id
        label = f"[{i}] {class_name}"
        
        # Use textbbox instead of textsize for newer Pillow versions
        bbox = draw.textbbox((0, 0), label, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        draw.rectangle([xmin, ymin - text_h - 4, xmin + text_w + 6, ymin], fill=color)
        draw.text((xmin + 3, ymin - text_h - 2), label, fill="black", font=font)

    if out_path is None:
        base, _ = os.path.splitext(image_path)
        out_path = base + "_bboxes.png"
    
    # Convert RGBA to RGB if saving as JPEG
    if out_path.lower().endswith(('.jpg', '.jpeg')):
        im = im.convert("RGB")
    
    im.save(out_path)
    print("Saved:", out_path)

def load_coco_json(json_path):
    """Load COCO JSON segmentation file"""
    with open(json_path, 'r') as f:
        return json.load(f)

def visualize_segmentation(json_path, output_path=None):
    """
    Visualize the image with segmentation masks overlayed
    
    Args:
        json_path: Path to the COCO JSON file
        output_path: Optional path to save the visualization
    """
    
    # Load JSON first to get image path
    if not os.path.exists(json_path):
        print(f"Error: JSON file not found: {json_path}")
        return
    
    coco_data = load_coco_json(json_path)
    
    # Extract image path from JSON
    if 'images' not in coco_data or len(coco_data['images']) == 0:
        print("Error: No images found in JSON file")
        return
    
    # Get image path from JSON (relative to JSON file location)
    json_dir = os.path.dirname(json_path)
    relative_image_path = coco_data['images'][0]['file_name']
    image_path = os.path.join(json_dir, relative_image_path)
    
    # Normalize the path to handle '../' correctly
    image_path = os.path.normpath(image_path)
    
    # Load image
    if not os.path.exists(image_path):
        print(f"Error: Image file not found: {image_path}")
        return
    
    image = Image.open(image_path)
    
    # Load classes
    classes_path = os.path.join(json_dir, "classes.txt")
    classes = load_classes(classes_path)
    if not classes:
        print(f"Warning: classes.txt not found at {classes_path}")
    
    # Load bounding boxes from txt file
    txt_path = json_path.replace("_labels.json", ".txt")
    if os.path.exists(txt_path):
        boxes = load_txt(txt_path, classes)
        if boxes:
            draw_boxes(image_path, boxes, classes)
        else:
            print("No boxes found in", txt_path)
    else:
        print(f"Warning: TXT file not found: {txt_path}")

    # Create figure with subplots
    fig, axes = plt.subplots(1, 2, figsize=(16, 8))
    
    # Show original image
    axes[0].imshow(image)
    axes[0].set_title('Original Image')
    axes[0].axis('off')
    
    # Show image with segmentation masks
    axes[1].imshow(image)
    axes[1].set_title('Image with Segmentation Masks')
    axes[1].axis('off')
    
    # Create category lookup
    categories = {cat['id']: cat['name'] for cat in coco_data['categories']}
    
    # Colors for different categories (not annotations)
    category_colors = {
        'ground': 'red',
        'bunny': 'blue',
        # Add more colors as needed
    }
    
    # Draw segmentation masks
    for i, annotation in enumerate(coco_data['annotations']):
        # Get category name
        category_id = annotation['category_id']
        category_name = categories.get(category_id, f'Category {category_id}')
        color = category_colors.get(category_name, plt.cm.Set3(i / len(coco_data['annotations'])))
        
        # Get segmentation polygon
        segmentation = annotation['segmentation'][0]  # Assuming single polygon per annotation
        
        # Convert flat list to (x, y) pairs
        points = []
        for j in range(0, len(segmentation), 2):
            points.append([segmentation[j], segmentation[j+1]])
        
        # Create polygon patch
        polygon = Polygon(points, closed=True, alpha=0.4, facecolor=color, edgecolor='black', linewidth=2)
        axes[1].add_patch(polygon)
        
        # Get bounding box
        bbox = annotation['bbox']
        rect = patches.Rectangle((bbox[0], bbox[1]), bbox[2], bbox[3], 
                               linewidth=2, edgecolor='red', facecolor='none', linestyle='--')
        axes[1].add_patch(rect)
        
        # Add annotation ID and category as text
        axes[1].text(bbox[0], bbox[1] - 5, f"ID: {annotation['id']} ({category_name})", 
                    color='white', fontsize=10, fontweight='bold',
                    bbox=dict(boxstyle="round,pad=0.3", facecolor='black', alpha=0.7))
    
    # Add legend with annotation info
    legend_text = []
    for i, annotation in enumerate(coco_data['annotations']):
        category_id = annotation['category_id']
        category_name = categories.get(category_id, f'Category {category_id}')
        legend_text.append(f"ID {annotation['id']}: {category_name}, Area {annotation['area']}")
    
    if legend_text:
        axes[1].text(0.02, 0.98, '\n'.join(legend_text), transform=axes[1].transAxes,
                    verticalalignment='top', bbox=dict(boxstyle="round,pad=0.5", facecolor='white', alpha=0.8))
    
    # Print summary
    print(f"Loaded image: {image.size[0]}x{image.size[1]}")
    print(f"Found {len(coco_data['annotations'])} segmentation masks")
    print(f"Categories: {[cat['name'] for cat in coco_data['categories']]}")
    
    plt.tight_layout()
    
    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"Visualization saved to: {output_path}")
    
    #plt.show()

def main():
    parser = argparse.ArgumentParser(description='Visualize COCO JSON segmentation masks')
    parser.add_argument('--json', default='cmake-build-release/bunnycam_segmentation.json',
                       help='Path to the COCO JSON segmentation file')
    parser.add_argument('--output', help='Optional output path for saving the visualization')
    
    args = parser.parse_args()
    
    # Check if we're in the right directory
    if not os.path.exists(args.json):
        print("JSON file not found in current directory. Looking in cmake-build-release/")
        args.json = 'cmake-build-release/bunnycam_segmentation.json'
    
    visualize_segmentation(args.json, args.output)

    


if __name__ == "__main__":
    main()