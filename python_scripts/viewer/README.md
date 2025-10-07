# Plant Simulation Data Viewer

Two viewer options for browsing images with labels and parameters:

## Local GUI Viewer (viewer.py)

For local use with GUI access - opens a popup window:

```bash
# Install dependencies
pip install matplotlib pillow

# Run viewer (opens GUI window)
python viewer.py /path/to/data/folder
```

## Web Viewer (web_viewer.py)

For remote access via web browser:

```bash
# Install dependencies  
pip install flask pillow

# Run viewer
python web_viewer.py /path/to/data/folder

# Set up SSH tunnel (on local machine)
ssh -N -L 7070:<server-ip>:7070 user@your-server

# Open in browser
http://localhost:7070
```

## Data Format Expected

```
folder/
├── 0000.jpeg
├── 0000_labels.json     # COCO format (optional)
├── 0000_params.json     # Any JSON structure (optional)
├── 0001.jpeg
├── 0001_labels.json
├── 0001_params.json
└── ...
```

## Usage Options

**Local GUI**: Use `viewer.py` when you have direct access to the machine with GUI
**Remote Web**: Use `web_viewer.py` when accessing a remote server via SSH

## Remote Access Setup

### With code-server

If you're using code-server:

1. **VS Code Port Forwarding** (Easiest):
   ```bash
   # In code-server terminal:
   python web_viewer.py /path/to/data --port 7070
   
   # In VS Code: Ctrl+Shift+P → "Ports: Focus on Ports View" → Forward port 7070
   ```

2. **SSH Tunnel**:
   ```bash
   # On local machine:
   ssh -N -L 7070:<server-ip>:7070 user@your-server
   
   # On server:
   python web_viewer.py /path/to/data --port 7070
   
   # Open: http://localhost:7070
   ```

### Direct SSH Access

```bash
# On local machine:
ssh -N -L 7070:<server-ip>:7070 user@your-server

# On server:
python web_viewer.py /path/to/data --port 7070

# Open: http://localhost:7070
```

## Troubleshooting

- **Connection refused**: Make sure the port isn't blocked by firewall
- **Empty page**: Check that the data folder contains images
- **No labels showing**: Verify JSON files follow COCO format
- **Slow loading**: Large images are automatically compressed for web display