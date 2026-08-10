#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
build_dir="${project_root}/build/cpp_lowstate_diagnostic"
sdk_root="${UNITREE_SDK_ROOT:-/home/unitree/unitree_sdk2-g1}"

cmake -S "${project_root}/cpp_lowstate_diagnostic" -B "${build_dir}" \
  -DUNITREE_SDK_ROOT="${sdk_root}" \
  -DBUILD_UNITREE_DIAGNOSTIC=ON -DBUILD_LOGIC_TESTS=ON
cmake --build "${build_dir}" -j2
(
  cd "${build_dir}"
  ctest --output-on-failure
)
echo "Binario listo: ${build_dir}/g1_lowstate_diagnostic"
