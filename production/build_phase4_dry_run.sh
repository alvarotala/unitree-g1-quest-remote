#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
build_dir="${project_root}/build/phase4"
sdk_root="${UNITREE_SDK_ROOT:-/home/unitree/unitree_sdk2-g1}"

cmake -S "${project_root}/phase4" -B "${build_dir}" \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_UNITREE_DRY_RUN=ON \
  -DUNITREE_SDK_ROOT="${sdk_root}"
cmake --build "${build_dir}" -j2
(
  cd "${build_dir}"
  ctest --output-on-failure
)

echo "Dry-run listo: ${build_dir}/g1_arm_dry_run"
