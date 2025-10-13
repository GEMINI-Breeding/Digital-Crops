# Editing `params.json`

Compatible sampling types: constant, uniform, discrete and normal.

Here are the formats based on the sampling type:

- constant : `{ "sampling": "constant", "value": 50.0 }`
- uniform : `{ "sampling": "uniform", "min": 1.0, "max": 4.0 }`
- discrete : `{ "sampling": "discrete", "values": [2, 4, 6, 7, 8] }`
- normal : `{ "sampling": "normal", "mean": 5.0, "stddev": 1.5 }`

# Adding new parameters

1. Add key and value pair in `params.json`
2. Define parameter name and type in `main.h` under `struct SampledParameters`. For example, if you want to include parameter height, define it as: `float camera_height;`
3. Include the same parameter in `main.cpp` under `sampleParameters` and `buildSampledParametersJson`. For example:
   - Under `sampleParameters`, I included:
     
     ```sampled.camera_height = sampleValue<float>(json_params["cameraproperties"]["camera_height"], rng);```
   - Under `buildSampledParametersJson`, I included:
     
     ```sampled_params["cameraproperties"]["camera_height"] = sampled.camera_height;```
