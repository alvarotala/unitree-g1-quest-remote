#!/usr/bin/env python3
"""Read-only probe for the native Unitree front-camera RTP multicast."""

import argparse
import socket
import struct
import time


def interface_ipv4(name):
    """Return an interface IPv4 address using Linux SIOCGIFADDR."""
    import fcntl

    request = struct.pack("256s", name[:15].encode("ascii"))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        response = fcntl.ioctl(sock.fileno(), 0x8915, request)
    return socket.inet_ntoa(response[20:24])


def rtp_header(packet):
    if len(packet) < 12 or packet[0] >> 6 != 2:
        return None
    extension_words = packet[0] & 0x0F
    header_size = 12 + 4 * extension_words
    if len(packet) < header_size:
        return None
    return {
        "marker": bool(packet[1] & 0x80),
        "payload_type": packet[1] & 0x7F,
        "sequence": struct.unpack_from("!H", packet, 2)[0],
        "timestamp": struct.unpack_from("!I", packet, 4)[0],
        "ssrc": struct.unpack_from("!I", packet, 8)[0],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Escucha pasivamente el RTP H.264 emitido por videohub_pc4."
    )
    parser.add_argument("--interface", default="eth0")
    parser.add_argument("--group", default="230.1.1.1")
    parser.add_argument("--port", type=int, default=1720)
    parser.add_argument("--duration", type=float, default=8.0)
    args = parser.parse_args()

    interface_address = interface_ipv4(args.interface)
    membership = socket.inet_aton(args.group) + socket.inet_aton(interface_address)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", args.port))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
    sock.settimeout(0.5)

    print("Unitree front-camera RTP probe (solo lectura)")
    print(f"Interfaz: {args.interface} ({interface_address})")
    print(f"Multicast: {args.group}:{args.port} | duracion: {args.duration:.1f} s")

    started = time.monotonic()
    packets = 0
    rtp_packets = 0
    byte_count = 0
    markers = 0
    gaps = 0
    malformed = 0
    payload_types = set()
    ssrcs = set()
    timestamps = set()
    last_sequence_by_ssrc = {}

    try:
        while time.monotonic() - started < args.duration:
            try:
                packet, _ = sock.recvfrom(65535)
            except socket.timeout:
                continue
            packets += 1
            byte_count += len(packet)
            header = rtp_header(packet)
            if header is None:
                malformed += 1
                continue
            rtp_packets += 1
            payload_types.add(header["payload_type"])
            ssrcs.add(header["ssrc"])
            timestamps.add((header["ssrc"], header["timestamp"]))
            markers += int(header["marker"])
            previous = last_sequence_by_ssrc.get(header["ssrc"])
            if previous is not None:
                distance = (header["sequence"] - previous) & 0xFFFF
                if 1 < distance < 0x8000:
                    gaps += distance - 1
            last_sequence_by_ssrc[header["ssrc"]] = header["sequence"]
    finally:
        sock.close()

    elapsed = max(time.monotonic() - started, 1e-6)
    bitrate_mbps = byte_count * 8.0 / elapsed / 1_000_000.0
    print()
    print("=== Resultado ===")
    print(f"UDP: {packets} paquetes | {byte_count} bytes | {bitrate_mbps:.3f} Mbit/s")
    print(f"RTP valido: {rtp_packets} | no RTP/malformados: {malformed}")
    if rtp_packets:
        print(f"Payload type: {sorted(payload_types)} | SSRC: {[hex(v) for v in sorted(ssrcs)]}")
        print(f"Marcadores de frame: {markers} | timestamps unicos: {len(timestamps)}")
        print(f"Huecos de secuencia observados: {gaps}")
        print("CONFIRMADO: el H.264 nativo puede reutilizarse sin abrir /dev/video4.")
        return 0

    print("SIN FLUJO: videohub_pc4 no emitio RTP durante esta ventana.")
    print("Abra el video en la app Unitree y repita la prueba mientras el feed este visible.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
