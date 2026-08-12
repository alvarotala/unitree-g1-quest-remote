#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
build_dir="${project_root}/build/phase4"

cmake -S "${project_root}/phase4" -B "${build_dir}" \
  -DCMAKE_BUILD_TYPE=Release
cmake --build "${build_dir}" -j2
(
  cd "${build_dir}"
  ctest --output-on-failure
)

echo "Supervisor Fase 4 verificado (sin DDS y sin publisher)."
