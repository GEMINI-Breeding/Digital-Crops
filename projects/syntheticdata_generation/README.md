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
