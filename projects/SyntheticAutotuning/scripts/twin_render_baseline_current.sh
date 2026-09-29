#!/bin/bash -l








# Naive baseline (rig LEDs only) rendered with the current harness and Helios, into baseline_<date>/render_current_sunoff.
# white-reference auto white balance, settings otherwise as twin_render_baseline.sh. Three lighting variants:
# sunconf (lighting as configured), sunspec (sun given the ASTM G173 spectrum), sunoff (rig LEDs only).
# Output in baseline_<date>/render_fixed_<variant>.
set -e
cd /group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning
source scripts/env.sh; unset DISPLAY
export OMP_NUM_THREADS=8
make -C build-gpu -j8 SyntheticAutotuning 2>&1 | grep -E "error|Built target SyntheticAutotuning" | head -5
cd build-gpu
W=/group/bnbaileygrp/bnbailey/Helios/projects/SyntheticAutotuning/twin_work
for V in sunoff; do
  case $V in
    sunconf) EXTRA="";;
    sunspec) EXTRA="light.sun_spectrum solar_spectrum_ASTMG173";;
    sunoff)  EXTRA="light.sun_flux 0";;
  esac
  for D in 2023-06-20 2023-06-27 2023-07-03; do
    B=$W/baseline_$D; echo "=== $V $B ==="; mkdir -p "$B/render_current_$V"
    ./SyntheticAutotuning render ../config/baseline.cfg 1 camera.hfov 71.884 camera.height 1.5 leaf.use_obj_mesh 0 \
      canopy.per_plant_seed 1 canopy.library_defaults 1 canopy.layout_file "$B/layout.txt" \
      leaf.nitrogen_model 0 leaf.chlorophyll 30 leaf.carotenoid 7 leaf.anthocyanin 1 leaf.numberlayers 1.5 leaf.watermass 0.015 leaf.drymass 0.09 \
      leaf.specular_scale 0 soil.reflectance_scale 1.0 soil.spectrum_index 0 scene.load_rover 1 $EXTRA \
      camera.exposure auto camera.white_balance auto post.white_balance 0 post.ccm_file "" post.highlight_knee 0 \
      camera.flux_smoothing 30 scene.ground_subdiv 500 camera.samples 40 output.write_exr 1 output.write_site_ids 1 \
      output.folder "$B/render_current_$V/" 2>&1 | grep -E "DIAG (sun_spectrum|canopy_top)|ERROR|WARNING \(Radiation|white balance|wrote " | head -6
  done
done
echo "=== done ==="
