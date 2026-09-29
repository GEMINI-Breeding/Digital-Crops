#!/bin/bash -l
#SBATCH --account=bnbaileygrp
#SBATCH --partition=gpu-6000_ada-h
#SBATCH --time=01:30:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH -J twin_specsat
#SBATCH -o /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/logs/twin_specsat-%j.out
# Naive baseline scenes, sun off, white-reference auto white balance, with leaf specular lowered and a saturation correction.
# leaf.specular_scale 0 does NOT turn specular off: when no primitive has a positive scale, Helios ignores the per-primitive
# scale and multiplies by 1, which is what the earlier baseline renders had. Off is leaf.specular_exponent -1.
# Output in baseline_<date>/render_<variant>.
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh; unset DISPLAY
export OMP_NUM_THREADS=8
make -C build-gpu -j8 SyntheticAutotuning 2>&1 | grep -E "error|Built target SyntheticAutotuning" | head -5
cd build-gpu
W=/group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/twin_work
for V in specoff_sat1 specoff_sat2 spec002_sat2; do
  case $V in
    specoff_sat1) EXTRA="leaf.specular_exponent -1 leaf.specular_scale 0 post.saturation 1.0";;
    specoff_sat2) EXTRA="leaf.specular_exponent -1 leaf.specular_scale 0 post.saturation 2.0";;
    spec002_sat2) EXTRA="leaf.specular_exponent 35 leaf.specular_scale 0.02 post.saturation 2.0";;
  esac
  for D in 2023-06-20 2023-06-27 2023-07-03; do
    B=$W/baseline_$D; echo "=== $V $B ==="; mkdir -p "$B/render_$V"
    ./SyntheticAutotuning render ../config/baseline.cfg 1 camera.hfov 71.884 camera.height 1.5 leaf.use_obj_mesh 0 \
      canopy.per_plant_seed 1 canopy.library_defaults 1 canopy.layout_file "$B/layout.txt" \
      leaf.nitrogen_model 0 leaf.chlorophyll 30 leaf.carotenoid 7 leaf.anthocyanin 1 leaf.numberlayers 1.5 leaf.watermass 0.015 leaf.drymass 0.09 \
      soil.reflectance_scale 1.0 soil.spectrum_index 0 scene.load_rover 1 light.sun_flux 0 \
      camera.exposure auto camera.white_balance auto post.white_balance 0 post.ccm_file "" post.highlight_knee 0 $EXTRA \
      camera.flux_smoothing 30 scene.ground_subdiv 500 camera.samples 40 output.write_exr 1 output.write_site_ids 1 \
      output.folder "$B/render_$V/" 2>&1 | grep -E "DIAG canopy_top|ERROR|WARNING \(Radiation|white balance|wrote " | head -6
  done
done
echo "=== done ==="
