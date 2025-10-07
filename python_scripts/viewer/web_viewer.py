#!/usr/bin/env python3
"""
Web-based Image + Labels + Params Viewer

Install:
  pip install flask pillow

Run:
  python web_viewer.py /path/to/folder --port 7070

Then access from your local machine:
  ssh -N -L 7070:<server-ip>:7070 user@your-server
  Open: http://localhost:7070
"""
import json
import argparse
import base64
from pathlib import Path
from typing import Dict, Any, List, Optional
from io import BytesIO

from flask import Flask, render_template_string, request, jsonify
from PIL import Image, ImageDraw

app = Flask(__name__)

# Global state
current_folder = None
images = []
current_idx = 0

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Plant Simulation Viewer</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
        .container { max-width: 1400px; margin: 0 auto; }
        .header { text-align: center; margin-bottom: 20px; }
        .content { display: flex; gap: 20px; }
        .image-panel { flex: 2; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .info-panel { flex: 1; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .navigation { text-align: center; margin: 20px 0; }
        .nav-btn { padding: 10px 20px; margin: 0 10px; background: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; }
        .nav-btn:hover { background: #0056b3; }
        .nav-btn:disabled { background: #ccc; cursor: not-allowed; }
        .image-container { text-align: center; margin-bottom: 20px; }
        .image-container img { max-width: 100%; height: auto; border: 1px solid #ddd; }
        .info-section { margin-bottom: 20px; }
        .info-title { font-weight: bold; margin-bottom: 10px; color: #333; border-bottom: 2px solid #007bff; padding-bottom: 5px; }
        .json-content { background: #f8f9fa; padding: 15px; border-radius: 4px; font-family: 'Courier New', monospace; font-size: 12px; white-space: pre-wrap; max-height: 400px; overflow-y: auto; }
        .counter { font-size: 18px; margin: 10px 0; }
        .filename { font-size: 14px; color: #666; margin-bottom: 10px; }
        .categories { margin-top: 10px; }
        .category { display: inline-block; background: #e9ecef; padding: 3px 8px; margin: 2px; border-radius: 3px; font-size: 12px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Plant Simulation Data Viewer</h1>
            <div class="counter">{{ current_idx + 1 }} / {{ total_images }}</div>
            <div class="filename">{{ filename }}</div>
        </div>
        
        <div class="navigation">
            <button class="nav-btn" onclick="navigate(-1)" {{ 'disabled' if current_idx == 0 else '' }}>← Previous</button>
            <button class="nav-btn" onclick="navigate(1)" {{ 'disabled' if current_idx >= total_images - 1 else '' }}>Next →</button>
        </div>
        
        <div class="content">
            <div class="image-panel">
                <div class="image-container">
                    {% if image_data %}
                        <img src="data:image/jpeg;base64,{{ image_data }}" alt="Current image">
                    {% else %}
                        <p>No image data available</p>
                    {% endif %}
                </div>
                
                {% if categories %}
                <div class="categories">
                    <strong>Categories:</strong>
                    {% for cat_id, cat_name in categories.items() %}
                        <span class="category">{{ cat_id }}: {{ cat_name }}</span>
                    {% endfor %}
                </div>
                {% endif %}
            </div>
            
            <div class="info-panel">
                {% if labels_data %}
                <div class="info-section">
                    <div class="info-title">Labels ({{ labels_filename }})</div>
                    <div class="json-content">{{ labels_data }}</div>
                </div>
                {% endif %}
                
                {% if params_data %}
                <div class="info-section">
                    <div class="info-title">Parameters ({{ params_filename }})</div>
                    <div class="json-content">{{ params_data }}</div>
                </div>
                {% endif %}
                
                {% if not labels_data and not params_data %}
                <div class="info-section">
                    <p>No additional data files found for this image.</p>
                </div>
                {% endif %}
            </div>
        </div>
    </div>
    
    <script>
        function navigate(direction) {
            fetch('/navigate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ direction: direction })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    location.reload();
                }
            });
        }
        
        // Keyboard navigation
        document.addEventListener('keydown', function(event) {
            if (event.key === 'ArrowLeft' || event.key === 'a') {
                navigate(-1);
            } else if (event.key === 'ArrowRight' || event.key === 'd') {
                navigate(1);
            }
        });
    </script>
</body>
</html>
"""


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


def draw_bboxes_on_image(image_path: Path, labels_json: Dict[str, Any]) -> Image.Image:
    """Draw bounding boxes on the image and return PIL Image."""
    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    
    # Parse COCO labels
    categories = {c.get("id"): c.get("name", str(c.get("id"))) for c in labels_json.get("categories", [])}
    anns = labels_json.get("annotations", []) or []
    images = labels_json.get("images", []) or []
    
    # Find matching image_id
    target_image_id = None
    if images:
        target_image_id = images[0]["id"]
        # Try to match by filename
        for img_rec in images:
            if Path(img_rec.get("file_name", "")).name == image_path.name:
                target_image_id = img_rec.get("id", target_image_id)
                break
    
    # Filter annotations
    if target_image_id is not None:
        anns = [a for a in anns if a.get("image_id") == target_image_id]
    
    # Draw bounding boxes
    colors = ["red", "blue", "green", "orange", "purple", "yellow", "cyan", "magenta"]
    for i, ann in enumerate(anns):
        bbox = ann.get("bbox")
        if bbox and len(bbox) == 4:
            x, y, w, h = bbox
            color = colors[i % len(colors)]
            # Draw rectangle
            draw.rectangle([x, y, x + w, y + h], outline=color, width=2)
            # Draw label
            cat_id = ann.get("category_id")
            label = f"{cat_id}: {categories.get(cat_id, 'Unknown')}"
            draw.text((x, y - 15), label, fill=color)
    
    return img


def image_to_base64(img: Image.Image) -> str:
    """Convert PIL Image to base64 string."""
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    img_str = base64.b64encode(buffer.getvalue()).decode()
    return img_str


def format_json_pretty(obj: Any) -> str:
    """Pretty format JSON with indentation."""
    return json.dumps(obj, indent=2, ensure_ascii=False)


@app.route('/')
def index():
    global current_folder, images, current_idx
    
    if not images:
        return "No images found in the specified folder."
    
    img_path = images[current_idx]
    stem = img_path.stem
    label_path = current_folder / f"{stem}_labels.json"
    params_path = current_folder / f"{stem}_params.json"
    
    # Load image and draw bboxes if labels exist
    labels_json = load_json_safely(label_path)
    if labels_json:
        img_with_boxes = draw_bboxes_on_image(img_path, labels_json)
        categories = {c.get("id"): c.get("name", str(c.get("id"))) for c in labels_json.get("categories", [])}
    else:
        img_with_boxes = Image.open(img_path).convert("RGB")
        categories = {}
    
    image_data = image_to_base64(img_with_boxes)
    
    # Load and format JSON data
    labels_data = None
    labels_filename = None
    if labels_json:
        labels_data = format_json_pretty(labels_json)
        labels_filename = label_path.name
    
    params_json = load_json_safely(params_path)
    params_data = None
    params_filename = None
    if params_json:
        params_data = format_json_pretty(params_json)
        params_filename = params_path.name
    
    return render_template_string(HTML_TEMPLATE,
                                current_idx=current_idx,
                                total_images=len(images),
                                filename=img_path.name,
                                image_data=image_data,
                                labels_data=labels_data,
                                labels_filename=labels_filename,
                                params_data=params_data,
                                params_filename=params_filename,
                                categories=categories)


@app.route('/navigate', methods=['POST'])
def navigate():
    global current_idx, images
    
    data = request.get_json()
    direction = data.get('direction', 0)
    
    if direction == -1 and current_idx > 0:
        current_idx -= 1
    elif direction == 1 and current_idx < len(images) - 1:
        current_idx += 1
    
    return jsonify({"success": True, "current_idx": current_idx})


def main():
    global current_folder, images
    
    parser = argparse.ArgumentParser(description="Web-based viewer for images with labels and parameters")
    parser.add_argument("--folder", help="Path to folder containing images and JSON files")
    parser.add_argument("--port", type=int, default=7070, help="Port for web server (default: 7070)")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    
    args = parser.parse_args()
    
    current_folder = Path(args.folder).expanduser().resolve()
    if not current_folder.exists():
        print(f"Folder not found: {current_folder}")
        return
    
    images = find_images(current_folder)
    if not images:
        print(f"No images found in {current_folder}")
        return
    
    print(f"Found {len(images)} images in {current_folder}")
    print(f"Starting web server on http://0.0.0.0:{args.port}")
    print("\nAccess options:")
    print(f"  SSH tunnel: ssh -N -L {args.port}:<server-ip>:{args.port} user@your-server")
    print(f"             then open http://localhost:{args.port}")
    print("\nPress Ctrl+C to stop the server")
    
    app.run(host="0.0.0.0", port=args.port, debug=False)


if __name__ == "__main__":
    main()