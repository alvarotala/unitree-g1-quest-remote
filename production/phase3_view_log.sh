#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Uso:
  ./production/phase3_view_log.sh [--ignore-deadman] [--speed N] quest-ID.ndjson

Descarga el log de PC2, ejecuta el retargeting offline y abre MuJoCo.
--ignore-deadman permite reproducir una captura sin ambos grips, solo offline.

Variables opcionales:
  UNITREE_SSH   destino SSH (por defecto: unitree@192.168.123.164)
EOF
}

ignore_deadman=0
speed="1"
log_name=""

while (($#)); do
  case "$1" in
    --ignore-deadman)
      ignore_deadman=1
      shift
      ;;
    --speed)
      if (($# < 2)); then
        echo "Falta el valor de --speed" >&2
        usage >&2
        exit 2
      fi
      speed="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      echo "Opcion desconocida: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      if [[ -n "${log_name}" ]]; then
        echo "Solo se permite un nombre de log" >&2
        usage >&2
        exit 2
      fi
      log_name="$1"
      shift
      ;;
  esac
done

if [[ ! "${log_name}" =~ ^quest-[A-Za-z0-9._-]+\.ndjson$ ]]; then
  echo "Nombre invalido: usa un archivo quest-ID.ndjson sin rutas" >&2
  usage >&2
  exit 2
fi

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
logs_dir="${project_root}/logs"
python_bin="${project_root}/.venv-phase3/bin/python"
mjpython_bin="${project_root}/.venv-phase3/bin/mjpython"
unitree_ssh="${UNITREE_SSH:-unitree@192.168.123.164}"
stem="${log_name%.ndjson}"
local_log="${logs_dir}/${log_name}"
report="${logs_dir}/${stem}-phase3-report.json"
trajectory="${logs_dir}/${stem}-phase3-trajectory.npz"

if [[ ! -x "${python_bin}" || ! -x "${mjpython_bin}" ]]; then
  echo "Falta .venv-phase3; sigue la preparacion de phase3/README.md" >&2
  exit 2
fi

mkdir -p "${logs_dir}"

echo "Descargando ${log_name} desde ${unitree_ssh}..."
rsync -av \
  "${unitree_ssh}:~/unitree-g1-quest-remote/logs/${log_name}" \
  "${logs_dir}/"

replay=(
  "${python_bin}" -m phase3.replay
  "${local_log}"
  --output "${report}"
  --trajectory "${trajectory}"
)
if ((ignore_deadman)); then
  replay+=(--simulation-ignore-deadman)
fi

echo "Generando trayectoria offline..."
cd "${project_root}"
if ! "${replay[@]}"; then
  echo >&2
  echo "El replay no fue aceptado; no se abrira el visualizador." >&2
  echo "Reporte: ${report}" >&2
  if ((ignore_deadman == 0)); then
    echo "Si la captura no uso ambos grips, repite con --ignore-deadman (solo simulacion)." >&2
  fi
  exit 1
fi

echo "Reporte: ${report}"
echo "Trayectoria: ${trajectory}"
echo "Abriendo MuJoCo..."
exec "${mjpython_bin}" -m phase3.view_trajectory "${trajectory}" --speed "${speed}"
