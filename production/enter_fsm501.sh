#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
confirmation="${1:-}"

if [[ "${confirmation}" != "G1_SUPPORTED_CLEAR" ]]; then
  echo "PRUEBA FISICA: ejecuta Damp durante 1 s, StandUp y luego solicita FSM 501." >&2
  echo "El G1 debe estar sujeto por gantry/soporte, con observador y parada lista." >&2
  echo "Uso: $0 G1_SUPPORTED_CLEAR" >&2
  exit 2
fi

if [[ ! -x "${project_root}/build/phase4/g1_vr_locomotion" ]]; then
  echo "Falta build/phase4/g1_vr_locomotion; compile primero." >&2
  exit 1
fi
if pgrep -f '[g]1_vr_locomotion' >/dev/null 2>&1; then
  echo "REFUSADO: ya existe g1_vr_locomotion activo." >&2
  exit 1
fi
if pgrep -f '[g]1_arm_dry_run' >/dev/null 2>&1; then
  echo "REFUSADO: g1_arm_dry_run sigue activo y posee el socket Quest." >&2
  exit 1
fi

exec "${project_root}/build/phase4/g1_vr_locomotion" \
  --interface eth0 \
  --duration 30 \
  --local-enable \
  --authorize-motion G1_VR_MOTION \
  --fsm-transition-only \
  --authorize-fsm-transition G1_DAMP_STAND_501
