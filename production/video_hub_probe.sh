#!/usr/bin/env bash
set -u

hub_dir="/unitree/module/video_hub_pc4"
hub_bin="${hub_dir}/videohub_pc4"

echo "=== CycloneDDS del video hub ==="
sed -n '1,240p' "${hub_dir}/cyclonedds.xml" 2>&1

echo
echo "=== Dependencias del video hub ==="
ldd "${hub_bin}" 2>&1

echo
echo "=== Cadenas relevantes del binario ==="
if command -v strings >/dev/null 2>&1; then
  strings -a "${hub_bin}" 2>/dev/null | \
    grep -Ei '(^|[^a-z])(rt/|topic|video|camera|image|frame|h264|h265|hevc|jpeg|nvenc|udp|webrtc|stream|dds|request|response)' | \
    sort -u | head -400
else
  echo "strings no disponible"
fi

echo
echo "=== Símbolos dinámicos relevantes ==="
readelf -Ws "${hub_bin}" 2>/dev/null | \
  grep -Ei 'video|image|frame|h264|jpeg|dds|channel|publisher|subscriber|socket|sendto' | \
  head -240 || true

echo
echo "=== Configuración nginx relacionada ==="
grep -RniE 'video|camera|stream|webrtc|rtsp|h264|jpeg' \
  /etc/nginx /unitree/etc /unitree/module 2>/dev/null | head -300 || true

echo
echo "=== IDL y headers de video instalados ==="
find /unitree /usr/local/include /usr/include -type f \
  \( -iname '*video*' -o -iname '*image*' -o -iname '*camera*' \) \
  2>/dev/null | head -300

echo
echo "=== Herramientas DDS disponibles ==="
for name in ddsls ddsspy cyclonedds-idlc idlc ros2; do
  command -v "${name}" 2>/dev/null || true
done

echo
echo "Inspección finalizada: no se abrió la cámara ni se modificó video_hub_pc4."
