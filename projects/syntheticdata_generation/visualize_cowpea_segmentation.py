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

# Removed draw_boxes in favor of single matplotlib rendering

def load_coco_json(json_path):
    """Load COCO JSON segmentation file"""
    with open(json_path, 'r') as f:
        return json.load(f)

def visualize_segmentation(json_path, output_path=None, box_source='txt'):
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
    
    # Load bounding boxes based on source
    boxes = []
    if box_source == 'txt':
        txt_path = json_path.replace("_masks.json", "_boxes.txt")
        if os.path.exists(txt_path):
            boxes = load_txt(txt_path, classes)
            if not boxes:
                print("No boxes found in", txt_path)
        else:
            print(f"Warning: TXT file not found: {txt_path}")
    else:
        # Extract boxes from JSON (COCO format: [xmin, ymin, w, h])
        W, H = image.size
        for ann in coco_data['annotations']:
            cls_id = str(ann['category_id'])
            xmin, ymin, bw, bh = ann['bbox']
            # Convert to normalized YOLO format (x_center, y_center, width, height)
            x_c = (xmin + bw/2) / W
            y_c = (ymin + bh/2) / H
            w = bw / W
            h = bh / H
            boxes.append((cls_id, x_c, y_c, w, h))
        print(f"Extracted {len(boxes)} boxes from JSON")

    # We will use matplotlib to draw both masks and boxes.

    # Create figure with exact image dimensions
    dpi = 100
    W_img, H_img = image.size
    fig = plt.figure(figsize=(W_img/dpi, H_img/dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    
    # Show image
    ax.imshow(image)
    ax.axis('off')
    
    # Create category lookup
    categories = {cat['id']: cat['name'] for cat in coco_data['categories']}
    
    # Draw segmentation masks
    for i, annotation in enumerate(coco_data['annotations']):
        # Get category name
        category_id = annotation['category_id']
        category_name = categories.get(category_id, f'Category {category_id}')
        
        # Color based on category ID to be consistent
        color = plt.cm.Set3(category_id / (max(categories.keys()) + 1))
        
        # Get segmentation polygon
        if 'segmentation' in annotation and annotation['segmentation']:
            segmentation = annotation['segmentation'][0]
            # Convert flat list to (x, y) pairs
            points = []
            for j in range(0, len(segmentation), 2):
                points.append([segmentation[j], segmentation[j+1]])
            
            # Create polygon patch
            polygon = Polygon(points, closed=True, alpha=0.4, facecolor=color, edgecolor='black', linewidth=1)
            ax.add_patch(polygon)
        
    if box_source == 'txt':
        # Draw Bounding Boxes from YOLO TXT
        # YOLO format is (cls, xc, yc, w, h) normalized
        box_colors = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4"]
        for i, (cls_id, x_c, y_c, w, h) in enumerate(boxes):
            if w > 0.8 or h > 0.8:
                continue # Skip huge boxes
            
            xc = x_c * W_img
            yc = y_c * H_img
            bw = w * W_img
            bh = h * H_img
            xmin = xc - bw/2
            ymin = yc - bh/2
            
            box_color = box_colors[int(cls_id) % len(box_colors)] if str(cls_id).isdigit() else "red"
            rect = patches.Rectangle((xmin, ymin), bw, bh, 
                                   linewidth=2, edgecolor=box_color, facecolor='none', linestyle='-')
            ax.add_patch(rect)
    else:
        # Draw Bounding Boxes from COCO JSON
        # COCO format is [xmin, ymin, width, height] in pixels
        box_colors = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4"]
        for annotation in coco_data['annotations']:
            if 'bbox' in annotation:
                bbox = annotation['bbox']
                
                # Filter out huge boxes
                w_norm = bbox[2] / W_img
                h_norm = bbox[3] / H_img
                if w_norm > 0.8 or h_norm > 0.8:
                    continue
                
                cat_id = annotation['category_id']
                box_color = box_colors[int(cat_id) % len(box_colors)]
                
                rect = patches.Rectangle((bbox[0], bbox[1]), bbox[2], bbox[3], 
                                       linewidth=2, edgecolor=box_color, facecolor='none', linestyle='-')
                ax.add_patch(rect)
    
    # Print summary
    print(f"Loaded image: {image.size[0]}x{image.size[1]}")
    print(f"Found {len(coco_data['annotations'])} segmentation masks")
    print(f"Categories: {[cat['name'] for cat in coco_data['categories']]}")
    
    if output_path:
        fig.savefig(output_path, dpi=dpi, bbox_inches=None, pad_inches=0)
        print(f"Visualization saved to: {output_path}")
    
    #plt.show()

def main():
    parser = argparse.ArgumentParser(description='Visualize COCO JSON segmentation masks')
    parser.add_argument('--json', default='cmake-build-release/bunnycam_segmentation.json',
                       help='Path to the COCO JSON segmentation file')
    parser.add_argument('--output', help='Optional output path for saving the visualization')
    parser.add_argument('--box-source', choices=['txt', 'json'], default='txt',
                       help='Source for bounding boxes: txt (YOLO format) or json (COCO format)')
    
    args = parser.parse_args()
    
    # Check if we're in the right directory
    if not os.path.exists(args.json):
        print("JSON file not found in current directory. Looking in cmake-build-release/")
        args.json = 'cmake-build-release/bunnycam_segmentation.json'
    
    visualize_segmentation(args.json, args.output, args.box_source)

    


if __name__ == "__main__":
    main()