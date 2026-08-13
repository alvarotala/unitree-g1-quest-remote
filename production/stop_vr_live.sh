#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
run_dir="${project_root}/run"

stop_one() {
  local name="$1" file="$2"
  if [[ ! -f "${file}" ]]; then
    echo "${name}: sin PID administrado"
    return
  fi
  local pid
  pid="$(sed -n '1p' "${file}")"
  if [[ ! "${pid}" =~ ^[0-9]+$ ]] || ! kill -0 "${pid}" 2>/dev/null; then
    echo "${name}: ya detenido"
    rm -f "${file}"
    return
  fi
  kill -INT "${pid}"
  for _ in $(seq 1 50); do
    kill -0 "${pid}" 2>/dev/null || break
    sleep 0.1
  done
  if kill -0 "${pid}" 2>/dev/null; then
    echo "${name}: no respondio a SIGINT; enviando SIGTERM"
    kill -TERM "${pid}"
  fi
  rm -f "${file}"
  echo "${name}: detenido"
}

# Primero locomocion: su salida ejecuta StopMove si alguna vez comando.
stop_one "locomocion" "${run_dir}/locomotion.pid"
stop_one "WebXR" "${run_dir}/web.pid"
