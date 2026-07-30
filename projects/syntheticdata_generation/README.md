# Editing `params.json`

Compatible sampling types: constant, uniform, discrete and normal.

Here are the formats based on the sampling type:

- constant : `{ "sampling": "constant", "value": 50.0 }`
- uniform : `{ "sampling": "uniform", "min": 1.0, "max": 4.0 }`
- discrete : `{ "sampling": "discrete", "values": [2, 4, 6, 7, 8] }`
- normal : `{ "sampling": "normal", "mean": 5.0, "stddev": 1.5 }`

## How Sampling Works

The system automatically discovers and samples ALL parameters in `params.json` that have a `"sampling"` key. When sampling occurs:

1. The system recursively traverses the entire JSON structure
2. Any parameter with a `"sampling"` key gets a `"sampled"` value added
3. The sampled value is stored alongside the original parameter definition

**Example:**
```json
// Before sampling:
"camera_height": { "sampling": "uniform", "min": 1.0, "max": 2.0 }

// After sampling:
"camera_height": { "sampling": "uniform", "min": 1.0, "max": 2.0, "sampled": 1.47 }
```

## Adding New Parameters

Adding new parameters is extremely simple - **no code changes required!**

1. **Add the parameter to `params.json`** with a sampling configuration:
   ```json
   "new_parameter": { "sampling": "uniform", "min": 10, "max": 20 }
   ```

2. **Access it in your code** using the `["sampled"]` key:
   ```cpp
   float value = params["path"]["to"]["new_parameter"]["sampled"].get<float>();
   ```

That's it! The recursive sampling function automatically:
- Discovers your new parameter
- Applies the appropriate sampling method
- Adds the sampled value to the JSON
- Makes it available for use in your code

## Parameter Structure

Parameters are organized hierarchically in `params.json`:

- `ground` - Ground/terrain parameters
- `sun_position` - Sun lighting parameters
- `plantarchitecture` - Plant growth and structure parameters
- `cameraproperties` - Camera positioning and settings
- `radiationmodel` - Spectral data and material properties

Each section can contain any number of parameters with sampling configurations.

## Output Files

For each crop iteration, the system generates:

- `crop_XXXX_params.json` - Full parameter file with both:
  - Original parameter definitions (sampling configuration)
  - Sampled values (the actual values used for that iteration)

The original `params.json` configuration is also saved once as `original_params.json` for reference.

## Non-Sampled Parameters

Parameters without a `"sampling"` key (like file paths or constant strings) are kept as-is:

```json
"colorboard": "plugins/radiation/spectral_data/ColorCheckerPassportPhoto_spectrum.xml"
```

These values remain unchanged in the output files.

---

# Running `main`

The executable is named `main`. It is built in the `build/` directory and reads parameters from `params.json` (relative to the build directory by default).

## Basic Usage

```bash
./main [OPTIONS]
```

```bash
# Render a cowpea at DAP 10 using the default renderer (both visualizer and radiation)
./main -n "cowpea" --dap 10

# Render only the OpenGL visualizer image (fast)
./main --renderer vis -n "cowpea" --dap 10

# Render only the radiation camera image
./main --renderer radiation -n "cowpea" --dap 10

# Same with a 5 m camera height
./main --renderer vis -n "cowpea" --dap 10 --height 5
```

## Command-Line Options

All options listed below can be combined. When multiple options affect the same value, the later-applied option wins (see `--focus-plant` for an example).

### Renderer output

| Option | Default | Description |
|--------|---------|-------------|
| `--renderer MODE` | `all` | Select output renderer. One of `vis`, `radiation`, `all`, or `none`. |
| `--save-xml` | on | Save plant structure XML files. |
| `--no-save-xml` | — | Skip saving XML files. |

`--renderer` values:

- `vis` — Generate the OpenGL visualizer RGB image (`*_vis.jpeg`).
- `radiation` — Generate the physics-based radiation camera image (`*_rad.jpeg`), plus optional multispectral/thermal/depth/WUE maps.
- `all` — Generate both visualizer and radiation images (default).
- `none` — Skip all image generation. Useful with `--stats-only` or `--dry-run`.

### Boolean / on-off flags

| Option | Description |
|--------|-------------|
| `-d`, `--debug` | Enable debug logging. Prints detailed parameter lookup traces. |
| `-r`, `--rotation` | Enable rotation view. |
| `-g`, `--grow` | Enable grow mode. |
| `--stats-only` | Only output statistics; skip image generation. |
| `--gui` | Launch the interactive GUI mode (requires OpenGL/GLFW display). |
| `--dry-run` | Load and validate `params.json` without running generation. |
| `--focus-plant` | Auto-fit the horizontal FOV to the plant's actual XY bounding box plus a 5% margin. Affects whichever renderer is active. |

### Options that take `true`/`false` (or `1`/`0`)

| Option | Default | Description |
|--------|---------|-------------|
| `--calibrate-color true\|false` | `false` | Add a color calibration panel and auto-calibrate the output image. |
| `--multispectral true\|false` | `false` | Generate a multispectral (NIR) image (only with `--renderer radiation` or `all`). |
| `--temperature`, `--thermal` `true\|false` | `false` | Generate a temperature (LW) image (only with `--renderer radiation` or `all`). |
| `--depth` `true\|false` | `false` | Generate a depth map image (only with `--renderer radiation` or `all`). |
| `--wue`, `--run_wue` `true\|false` | `false` | Generate a Water-Use Efficiency (WUE) image (only with `--renderer radiation` or `all`). |

### Options that take a numeric / string argument

| Option | Argument | Description |
|--------|----------|-------------|
| `-h`, `--height` | `HEIGHT` | Override the camera height in meters. The default is read from `params.json` (`camera.positioning.camera_height`). |
| `--fov` | `DEGREES` | Override the horizontal FOV in degrees. By default the FOV is auto-calculated from the field size and camera height. |
| `--dap`, `--days` | `N` | Override DAP (days-after-planting) from `params.json` metadata. Useful for forcing a specific plant age. |
| `-s`, `--seed` | `N` | Set the random seed for reproducible sampling. |
| `-i`, `--iteration` | `N` | Set the number of iterations to run. |
| `-n`, `--name` | `NAME` | Set the output base name (default: `plot`). |
| `-o`, `--output` | `DIR` | Set the output directory. |
| `-f`, `--file` | `FILE` | Use a different parameter file instead of the default `params.json`. |
| `-t`, `--tile` | `FILE` | Set the tile file path. |

## Camera Control Deep Dive

Three mechanisms determine the final camera horizontal FOV (`HFOV`). They are applied in this order, so later steps override earlier ones:

1. **Field-based auto FOV** (default): `init_camera()` calculates `ground_x = plot_size_x * num_beds`, then computes the FOV that exactly covers the field at the current camera height.
2. **`--fov DEGREES`**: directly replaces the field-based HFOV.
3. **`--focus-plant`**: after plant aging, computes the plant's XY bounding box from all 3D vertices and recalculates HFOV with a 5% margin. This overrides `--fov` because it runs later.

Both options store the final value in `camera_setup.cam_prop.HFOV`, and both renderers use it:

- OpenGL visualizer:
  ```cpp
  vis.setCameraFieldOfView(HFOVtoVFOV(cam_prop.HFOV, aspect_ratio));
  ```
- Radiation camera: the radiation camera is registered with the same `cam_prop` *after* `--focus-plant` runs, so the focused FOV is applied to the physics-based render as well.

### Examples

```bash
# Default field-based FOV
./main --renderer vis -n "cowpea" --dap 10

# Manually set a 45-degree horizontal FOV
./main --renderer vis -n "cowpea" --dap 10 --fov 45
# [INFO] HFOV overridden by --fov flag: 45 degrees

# Auto-fit FOV to the plant bounding box (works for both renderers)
./main --renderer all -n "cowpea" --dap 10 --focus-plant
# [INFO] --focus-plant: plant XY span = 0.42 x 0.38 m, camera_height = 5 m, new HFOV = 5.1 deg

# Tight radiation-only close-up with focused FOV
./main --renderer radiation -n "cowpea" --dap 10 --height 1 --focus-plant
# [INFO] --focus-plant: plant XY span = 0.104 x 0.081 m, camera_height = 1 m, new HFOV = 5.96 deg
```

Because DAP changes plant size, `--focus-plant` keeps the plant filling the frame regardless of age or renderer. Use `--height` together with `--focus-plant` to also control perspective.

## Common Workflows

```bash
# Fast RGB-only visualizer render
./main --renderer vis -n "cowpea" --dap 10

# Physics-based radiation image only
./main --renderer radiation -n "cowpea" --dap 10

# Both images at once (default)
./main -n "cowpea" --dap 10

# High camera overview of a mature plant
./main --renderer vis -n "cowpea" --dap 61 --height 5

# Tight close-up with plant-centered framing
./main --renderer radiation -n "cowpea" --dap 61 --height 1 --focus-plant

# Reproducible render with a fixed seed
./main --renderer vis -n "cowpea" --dap 10 --seed 42

# No images, just validate JSON and print stats
./main --renderer none --dry-run -n "cowpea"
```

---

# Setting up Vulkan on macOS

macOS (Apple Silicon M1/M2/M3/M4 and Intel Mac) does not ship a native Vulkan driver. Helios's radiation plugin uses the Khronos **MoltenVK** runtime, which translates Vulkan API calls into Apple's Metal API.

## Option 1: Install via Homebrew (recommended)

Install the Vulkan loader, headers, and MoltenVK runtime:

```bash
brew install vulkan-headers vulkan-loader molten-vk vulkan-tools
```

Add environment variables to `~/.zshrc` so CMake and the loader can find the libraries. The example below assumes an Apple Silicon Mac with Homebrew in `/opt/homebrew`; Intel Mac users should use `/usr/local` instead.

```bash
# ~/.zshrc
export VULKAN_SDK=/opt/homebrew
export PATH=$VULKAN_SDK/bin:$PATH
export DYLD_LIBRARY_PATH=$VULKAN_SDK/lib:$DYLD_LIBRARY_PATH
export VK_ICD_FILENAMES=$VULKAN_SDK/share/vulkan/icd.d/MoltenVK_icd.json
export VK_DRIVER_FILES=$VULKAN_SDK/share/vulkan/icd.d/MoltenVK_icd.json
```

Apply the changes:

```bash
source ~/.zshrc
```

## Option 2: Install the official LunarG Vulkan SDK

1. Download the latest **Vulkan SDK for macOS** from the [LunarG download page](https://vulkan.lunarg.com/sdk/home).
2. Open the `.dmg` installer and follow the instructions.
3. After installation, the SDK is placed under `~/VulkanSDK/<version>/macOS`. Run the included `setup-env.sh` script before building, or export `VULKAN_SDK` to that path.

## Verify the installation

Check that Vulkan can see the Metal-backed GPU:

```bash
vulkaninfo --summary
```

Expected output (Apple Silicon example):

```text
Devices:
========
GPU0:
	apiVersion     = 1.2.0
	driverVersion  = 1.2.0
	vendorID       = 0x106b (Apple)
	deviceID       = 0x0000
	deviceType     = PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU
	deviceName     = Apple M1 / M2 / M3 / M4
	driverName     = MoltenVK
```

You can also run the rotating cube demo to confirm rendering works:

```bash
vkcube
```

## Build Helios with the Vulkan backend

Once Vulkan is installed, configure the project with the Vulkan backend forced on:

```bash
cd Digital-Crops/projects/syntheticdata_generation/build
cmake -DFORCE_VULKAN_BACKEND=ON -DCMAKE_POLICY_VERSION_MINIMUM=3.5 ..
make -j4
```

Note: the radiation plugin auto-detects CUDA/OptiX on platforms that support it. On macOS, only the Vulkan backend is available, so `FORCE_VULKAN_BACKEND=ON` is the recommended way to ensure it is selected.
