#!/usr/bin/env bash
set -u

echo "=== Dispositivos de video ==="
found=0
for device in /dev/video*; do
  [[ -e "${device}" ]] || continue
  found=1
  ls -l "${device}"
  device_name="/sys/class/video4linux/${device##*/}/name"
  [[ -r "${device_name}" ]] && sed -n '1p' "${device_name}"
  if command -v udevadm >/dev/null 2>&1; then
    udevadm info --query=property --name="${device}" 2>/dev/null | \
      grep -E '^(ID_V4L_|ID_MODEL=|ID_VENDOR=|ID_PATH=)' || true
  fi
  if command -v fuser >/dev/null 2>&1; then
    users="$(fuser "${device}" 2>/dev/null || true)"
    [[ -n "${users}" ]] && echo "PIDs con dispositivo abierto:${users}"
  fi
done
((found)) || echo "No se encontraron /dev/video*"

echo
echo "=== V4L2 ==="
if command -v v4l2-ctl >/dev/null 2>&1; then
  v4l2-ctl --list-devices 2>&1
  for device in /dev/video*; do
    [[ -e "${device}" ]] || continue
    echo "--- ${device} ---"
    v4l2-ctl --device "${device}" --all 2>&1 | head -80
    v4l2-ctl --device "${device}" --list-formats-ext 2>&1 | head -120
  done
else
  echo "v4l2-ctl no instalado"
fi

if command -v gst-device-monitor-1.0 >/dev/null 2>&1; then
  echo
  echo "=== Fuentes detectadas por GStreamer ==="
  timeout 8 gst-device-monitor-1.0 Video/Source 2>&1 | head -240
fi

echo
echo "=== Herramientas multimedia ==="
for command_name in gst-launch-1.0 gst-inspect-1.0 ffmpeg; do
  if command -v "${command_name}" >/dev/null 2>&1; then
    command -v "${command_name}"
    "${command_name}" --version 2>&1 | head -2
  else
    echo "${command_name}: no instalado"
  fi
done

echo
echo "=== Plugins utiles ==="
for plugin in v4l2src jpegdec videoconvert x264enc omxh264enc nvv4l2h264enc \
              webrtcbin rtph264pay; do
  if gst-inspect-1.0 "${plugin}" >/dev/null 2>&1; then
    echo "${plugin}: disponible"
  else
    echo "${plugin}: no disponible"
  fi
done

echo
echo "=== Puertos UDP/TCP relacionados con video ==="
ss -lntup 2>&1 | grep -Ei 'videohub|rtsp|webrtc|camera|video|8554|554|8080|8081|8888' || \
  echo "No se detectaron puertos conocidos por nombre"

echo
echo "=== Descriptores del video hub ==="
for pid in $(pgrep -f '/unitree/module/video_hub_pc4/' 2>/dev/null); do
  echo "--- PID ${pid} ---"
  ps -p "${pid}" -o pid,user,comm,args
  for descriptor in /proc/"${pid}"/fd/*; do
    target="$(readlink "${descriptor}" 2>/dev/null || true)"
    case "${target}" in
      /dev/video*|socket:*) echo "${descriptor##*/} -> ${target}" ;;
    esac
  done
done

echo
echo "=== Procesos relacionados con video ==="
ps -eo pid,comm,args 2>&1 | grep -Ei 'camera|video|gstreamer|gst-launch|ffmpeg|rtsp|webrtc' | \
  grep -v -E 'grep|camera_probe' || echo "No se detectaron procesos conocidos"

echo
echo "Diagnostico finalizado: solo lectura; no se inicio ningun stream."
