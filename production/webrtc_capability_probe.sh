#!/usr/bin/env bash
set -u

failed=0

echo "=== GStreamer ==="
gst-launch-1.0 --version 2>&1 | head -2
printf 'Arquitectura: '
dpkg --print-architecture 2>/dev/null || uname -m
if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  printf 'Sistema: %s\n' "${PRETTY_NAME:-desconocido}"
fi

echo
echo "=== Bindings Python ==="
if python3 -c 'import gi; gi.require_version("Gst", "1.0"); gi.require_version("GstWebRTC", "1.0"); gi.require_version("GstSdp", "1.0"); from gi.repository import Gst, GstWebRTC, GstSdp; Gst.init(None); print("GI Gst/GstWebRTC/GstSdp: OK"); print("GStreamer:", Gst.version_string())'; then
  :
else
  echo "FALTA: bindings GI de GStreamer/WebRTC/SDP"
  failed=1
fi

echo
echo "=== Elementos requeridos ==="
for element in \
  udpsrc rtpjitterbuffer rtph264depay h264parse rtph264pay \
  webrtcbin dtlssrtpenc dtlssrtpdec srtpenc srtpdec nicesrc nicesink
do
  if gst-inspect-1.0 "${element}" >/dev/null 2>&1; then
    printf 'OK    %s\n' "${element}"
  else
    printf 'FALTA %s\n' "${element}"
    failed=1
  fi
done

echo
echo "=== Diagnostico libnice ==="
for package in gstreamer1.0-nice libnice10 libnice-dev; do
  if dpkg-query -W -f='${Status} ${Version}\n' "${package}" 2>/dev/null | grep -q '^install ok installed '; then
    printf '%-20s ' "${package}"
    dpkg-query -W -f='${Version}\n' "${package}"
  else
    printf '%-20s NO INSTALADO\n' "${package}"
  fi
done

nice_plugins="$(find /usr/lib /usr/local/lib /home/unitree -type f -name libgstnice.so 2>/dev/null | head -20)"
if [[ -n "${nice_plugins}" ]]; then
  echo "libgstnice.so encontrado:"
  printf '%s\n' "${nice_plugins}"
  while IFS= read -r plugin; do
    echo "Dependencias faltantes de ${plugin}:"
    ldd "${plugin}" 2>/dev/null | grep 'not found' || echo "  ninguna detectada por ldd"
  done <<< "${nice_plugins}"
else
  echo "libgstnice.so: NO ENCONTRADO"
fi
printf 'GST_PLUGIN_PATH=%s\n' "${GST_PLUGIN_PATH:-<vacio>}"

echo
echo "=== H.264 del flujo nativo ==="
echo "RTP multicast: 230.1.1.1:1720 / eth0 / PT 96 / 1280x720 / 15 FPS"
echo "El probe no inicia pipelines ni abre /dev/video4."

echo
if (( failed == 0 )); then
  echo "CAPACIDAD WEBRTC: OK"
else
  echo "CAPACIDAD WEBRTC: INCOMPLETA"
fi
exit "${failed}"
