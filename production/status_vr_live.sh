#!/usr/bin/env bash
set -u

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
run_dir="${project_root}/run"
service_log_dir="${project_root}/logs/services"

show_process() {
  local name="$1" file="$2"
  if [[ -f "${file}" ]]; then
    local pid
    pid="$(sed -n '1p' "${file}")"
    if [[ "${pid}" =~ ^[0-9]+$ ]] && kill -0 "${pid}" 2>/dev/null; then
      echo "${name}: ACTIVO (PID ${pid})"
      return
    fi
  fi
  echo "${name}: DETENIDO"
}

show_process "WebXR" "${run_dir}/web.pid"
show_process "Locomocion" "${run_dir}/locomotion.pid"

echo
echo "=== Supervisor ==="
if [[ -r /tmp/g1_quest_supervisor_status.json ]]; then
  python3 -m json.tool /tmp/g1_quest_supervisor_status.json 2>/dev/null || \
    cat /tmp/g1_quest_supervisor_status.json
else
  echo "sin estado fresco"
fi

echo
echo "=== Ultimas lineas locomocion ==="
tail -30 "${service_log_dir}/locomotion.log" 2>/dev/null || echo "sin log"

echo
echo "=== Ultimas lineas WebXR ==="
tail -15 "${service_log_dir}/web.log" 2>/dev/null || echo "sin log"
