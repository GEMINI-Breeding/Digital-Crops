#!/bin/bash
# Build environment for the SyntheticAutotuning Helios project.
# The cmake/gcc module PATH entries point at a spack "view" that is not
# populated on this node, so the concrete spack prefixes are used directly --
# these are the same paths recorded in the working Syn2Real_cowpea build cache.
export PATH=/cvmfs/hpc.ucdavis.edu/sw/spack/main/linux-ubuntu22.04-x86_64_v3/gcc-13.2.0/cmake-3.28.1-pm5f36g7jmvp4nkqlvw75kbpbvhowomi/bin:$PATH
GCCVIEW=/cvmfs/hpc.ucdavis.edu/sw/spack/environments/compilers/view/gcc-11.4.0
if [ -x "$GCCVIEW/bin/c++" ]; then
  export CC="$GCCVIEW/bin/gcc" CXX="$GCCVIEW/bin/c++"
  export PATH="$GCCVIEW/bin:$PATH"
fi
# CUDA. The concrete path is taken from `module show cuda/12.6.2`; the module
# itself is not loaded because the modules shell function is not always present
# in non-interactive SLURM steps. Without CUDA the radiation plugin silently
# falls back to its Vulkan software-BVH backend, which returns NaN for every
# camera pixel once plant geometry is in the scene -- a black image, not an error.
CUDA_VIEW=/cvmfs/hpc.ucdavis.edu/sw/spack/environments/core/view/generic/cuda-12.6.2
for c in "$CUDA_VIEW/bin" /usr/local/cuda/bin; do
  if [ -x "$c/nvcc" ]; then
    export PATH="$c:$PATH"
    export CUDACXX="$c/nvcc"
    export CUDA_HOME="$(dirname "$c")" CUDA_ROOT="$(dirname "$c")"
    export LD_LIBRARY_PATH="$(dirname "$c")/lib64:$LD_LIBRARY_PATH"
    export CMAKE_PREFIX_PATH="$(dirname "$c"):$CMAKE_PREFIX_PATH"
    break
  fi
done
# Always succeed: this file is sourced with `&&` chaining, and the nvcc probe
# above returns non-zero when CUDA is absent (which is not an error here --
# the radiation plugin falls back to its Vulkan backend).
true
