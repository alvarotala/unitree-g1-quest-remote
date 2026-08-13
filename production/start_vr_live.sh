#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
run_dir="${project_root}/run"
service_log_dir="${project_root}/logs/services"
web_pid_file="${run_dir}/web.pid"
loco_pid_file="${run_dir}/locomotion.pid"
web_log="${service_log_dir}/web.log"
loco_log="${service_log_dir}/locomotion.log"
quest_ip="192.168.100.209"
dds_interface="eth0"
duration="3600"
confirmation=""

usage() {
  echo "Uso: $0 --confirm-standing G1_STANDING_CLEAR [--ip IP] [--duration S]"
  echo "Inicia WebXR y locomocion REAL en background."
}

while (($#)); do
  case "$1" in
    --confirm-standing)
      (($# >= 2)) || { usage; exit 2; }
      confirmation="$2"; shift 2 ;;
    --ip)
      (($# >= 2)) || { usage; exit 2; }
      quest_ip="$2"; shift 2 ;;
    --duration)
      (($# >= 2)) || { usage; exit 2; }
      duration="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Opcion desconocida: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ "${confirmation}" != "G1_STANDING_CLEAR" ]]; then
  echo "REFUSADO: confirme robot de pie, suelo plano y area libre con:" >&2
  echo "  --confirm-standing G1_STANDING_CLEAR" >&2
  exit 2
fi
if [[ ! "${duration}" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "Duracion invalida: ${duration}" >&2
  exit 2
fi
if [[ ! -x "${project_root}/build/phase4/g1_vr_locomotion" ]]; then
  echo "Falta build/phase4/g1_vr_locomotion; compile primero." >&2
  exit 1
fi
if ! ip -br -4 addr show wlan0 | grep -q "${quest_ip}/"; then
  echo "wlan0 no tiene ${quest_ip}; use --ip con la direccion Wi-Fi actual." >&2
  exit 1
fi
if ! ip link show "${dds_interface}" >/dev/null 2>&1; then
  echo "No existe la interfaz DDS ${dds_interface}." >&2
  exit 1
fi

mkdir -p "${run_dir}" "${service_log_dir}"

alive_from_file() {
  local file="$1"
  [[ -f "${file}" ]] || return 1
  local pid
  pid="$(sed -n '1p' "${file}")"
  [[ "${pid}" =~ ^[0-9]+$ ]] && kill -0 "${pid}" 2>/dev/null
}

if alive_from_file "${web_pid_file}" || alive_from_file "${loco_pid_file}"; then
  echo "Ya hay servicios administrados activos. Ejecute production/status_vr_live.sh." >&2
  exit 1
fi
if pgrep -f 'g1_arm_dry_run' >/dev/null 2>&1; then
  echo "REFUSADO: g1_arm_dry_run sigue activo y posee el socket Quest." >&2
  exit 1
fi
if pgrep -f '[p]ython3 .*web/server.py' >/dev/null 2>&1; then
  echo "REFUSADO: hay un web/server.py manual activo. Detengalo con Ctrl-C primero." >&2
  exit 1
fi
if pgrep -f '[g]1_vr_locomotion' >/dev/null 2>&1; then
  echo "REFUSADO: ya existe un g1_vr_locomotion fuera del administrador." >&2
  exit 1
fi

: > "${web_log}"
: > "${loco_log}"
nohup python3 -u "${project_root}/web/server.py" \
  --ip "${quest_ip}" --camera-interface "${dds_interface}" \
  >> "${web_log}" 2>&1 &
web_pid=$!
echo "${web_pid}" > "${web_pid_file}"

web_ready=false
for _ in $(seq 1 30); do
  kill -0 "${web_pid}" 2>/dev/null || break
  if curl -kfsS --max-time 1 "https://${quest_ip}:8443/api/status" >/dev/null 2>&1; then
    web_ready=true
    break
  fi
  sleep 0.1
done
if [[ "${web_ready}" != true ]] || ! kill -0 "${web_pid}" 2>/dev/null; then
  echo "El servidor WebXR no inicio. Log:" >&2
  tail -40 "${web_log}" >&2
  kill -INT "${web_pid}" 2>/dev/null || true
  exit 1
fi

nohup stdbuf -oL -eL "${project_root}/build/phase4/g1_vr_locomotion" \
  --interface "${dds_interface}" \
  --duration "${duration}" \
  --local-enable \
  --authorize-motion G1_VR_MOTION \
  >> "${loco_log}" 2>&1 &
loco_pid=$!
echo "${loco_pid}" > "${loco_pid_file}"
sleep 1
if ! kill -0 "${loco_pid}" 2>/dev/null; then
  echo "La locomocion no inicio. Log:" >&2
  tail -60 "${loco_log}" >&2
  kill -INT "${web_pid}" 2>/dev/null || true
  exit 1
fi

echo "LIVE VR iniciado en background."
echo "Quest: https://${quest_ip}:8443"
echo "Web PID ${web_pid} | log ${web_log}"
echo "Loco PID ${loco_pid} | log ${loco_log}"
echo "Parada local: ${project_root}/production/stop_vr_live.sh"
echo "Estado:       ${project_root}/production/status_vr_live.sh"
echo "Damp y ZeroTorque permanecen BLOQUEADOS."
