#!/usr/bin/env python3
"""Small HTTPS server and read-only WebXR telemetry receiver.

This intentionally has no robot, DDS, or command capabilities.  It is the
Phase 2 transport probe: serve the Quest UI and record incoming poses.
"""

import argparse
import ipaddress
import json
import math
import socket
import ssl
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = WEB_ROOT.parent
LOG_DIR = PROJECT_ROOT / "logs"
CERT_DIR = PROJECT_ROOT / ".cert"
MAX_BODY_BYTES = 256 * 1024
MAX_SAMPLES_PER_BATCH = 120
STREAM_TIMEOUT_SECONDS = 0.75
SAFETY_SOCKET_PATH = "/tmp/g1_quest_safety.sock"
SUPERVISOR_STATUS_PATH = Path("/tmp/g1_quest_supervisor_status.json")
log_lock = threading.Lock()


def local_ip():
    """Return the address the host would use for a normal LAN connection."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("1.1.1.1", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def ensure_certificate(ip):
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    cert = CERT_DIR / "quest-local.crt"
    key = CERT_DIR / "quest-local.key"
    marker = CERT_DIR / "quest-local.ip"
    if cert.exists() and key.exists() and marker.exists() and marker.read_text().strip() == ip:
        return cert, key

    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256",
            "-days", "30", "-nodes", "-keyout", str(key), "-out", str(cert),
            "-subj", "/CN=Unitree G1 Quest Remote",
            "-addext", f"subjectAltName=IP:{ip},IP:127.0.0.1,DNS:localhost",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    marker.write_text(ip + "\n")
    return cert, key


def finite_number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def validate_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("expected a JSON object")
    if payload.get("protocolVersion") != 1:
        raise ValueError("unsupported protocolVersion")
    session = payload.get("sessionId")
    if not isinstance(session, str) or not 1 <= len(session) <= 80:
        raise ValueError("invalid sessionId")
    if any(not (character.isalnum() or character in "-_") for character in session):
        raise ValueError("invalid sessionId")
    samples = payload.get("samples")
    if not isinstance(samples, list) or not 1 <= len(samples) <= MAX_SAMPLES_PER_BATCH:
        raise ValueError("samples must contain between 1 and 120 entries")
    for sample in samples:
        if not isinstance(sample, dict):
            raise ValueError("every sample must be an object")
        sequence = sample.get("sequence")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise ValueError("invalid sample sequence")
        client_time = sample.get("clientTime")
        if not finite_number(client_time) or client_time < 0:
            raise ValueError("invalid sample clientTime")
    return session, samples


def tracked_controller(sample, side):
    controller = sample.get(side)
    return (isinstance(controller, dict) and
            isinstance(controller.get("grip") or controller.get("ray"), dict))


def grip_pressed(sample, side):
    controller = sample.get(side)
    buttons = controller.get("buttons") if isinstance(controller, dict) else None
    return (isinstance(buttons, list) and len(buttons) > 1 and
            isinstance(buttons[1], dict) and buttons[1].get("pressed") is True)


def button_pressed(sample, side, index):
    controller = sample.get(side)
    buttons = controller.get("buttons") if isinstance(controller, dict) else None
    return (isinstance(buttons, list) and len(buttons) > index and
            isinstance(buttons[index], dict) and buttons[index].get("pressed") is True)


def thumbstick(sample, side):
    controller = sample.get(side)
    axes = controller.get("axes") if isinstance(controller, dict) else None
    if not isinstance(axes, list) or len(axes) < 2:
        return 0.0, 0.0
    x, y = axes[-2:]
    if not finite_number(x) or not finite_number(y):
        return 0.0, 0.0
    return max(-1.0, min(1.0, float(x))), max(-1.0, min(1.0, float(y)))


def safety_datagram(session, sample):
    tracking = (isinstance(sample.get("head"), dict) and
                tracked_controller(sample, "left") and
                tracked_controller(sample, "right"))
    left_grip = grip_pressed(sample, "left")
    right_grip = grip_pressed(sample, "right")
    deadman = left_grip and right_grip
    left_x, left_y = thumbstick(sample, "left")
    right_x, right_y = thumbstick(sample, "right")
    face = [button_pressed(sample, side, index)
            for side, index in (("left", 4), ("left", 5),
                                ("right", 4), ("right", 5))]
    triggers = [button_pressed(sample, side, 0) for side in ("left", "right")]
    return (f"G1Q2 {session} {sample['sequence']} "
            f"{int(tracking)} {int(deadman)} "
            f"{int(left_grip)} {int(right_grip)} "
            f"{left_x:.4f} {left_y:.4f} {right_x:.4f} {right_y:.4f} "
            f"{int(triggers[0])} {int(triggers[1])} "
            f"{' '.join(str(int(value)) for value in face)}\n").encode("ascii")


def send_safety_datagram(session, sample, socket_path=SAFETY_SOCKET_PATH):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        sock.sendto(safety_datagram(session, sample), socket_path)
    except OSError:
        pass  # El consumidor dry-run es opcional.
    finally:
        sock.close()


def read_supervisor_status(path=SUPERVISOR_STATUS_PATH, now=None):
    now = time.time() if now is None else now
    fallback = {
        "state": "OFFLINE", "reason": "supervisor no iniciado",
        "fresh": False, "wouldPublish": False, "localEnable": False,
    }
    try:
        stat = path.stat()
        if now - stat.st_mtime > 0.5:
            return {**fallback, "reason": "estado del supervisor vencido"}
        value = json.loads(path.read_text(encoding="utf-8"))
        required = {"state", "reason", "wouldPublish", "localEnable",
                    "tracking", "deadman", "questAgeMs", "lowstateAgeMs"}
        if not isinstance(value, dict) or not required.issubset(value):
            return {**fallback, "reason": "estado del supervisor invalido"}
        return {**value, "fresh": True}
    except (OSError, json.JSONDecodeError):
        return fallback


@dataclass
class SessionStats:
    session_id: str
    first_received: float
    last_received: float
    last_sequence: int = None
    last_client_time: float = None
    received_samples: int = 0
    estimated_lost: int = 0
    duplicates: int = 0
    out_of_order: int = 0
    head_invalid: int = 0
    left_invalid: int = 0
    right_invalid: int = 0
    interval_count: int = 0
    interval_mean_ms: float = 0.0
    interval_m2: float = 0.0
    recent_rtt_ms: deque = field(default_factory=lambda: deque(maxlen=60))
    recent_clock_offset_ms: deque = field(default_factory=lambda: deque(maxlen=60))

    def observe(self, samples, received_at, client_metrics=None):
        self.last_received = received_at
        for sample in samples:
            sequence = sample["sequence"]
            client_time = float(sample["clientTime"])
            if self.last_sequence is not None:
                if sequence == self.last_sequence:
                    self.duplicates += 1
                elif sequence < self.last_sequence:
                    self.out_of_order += 1
                else:
                    if sequence > self.last_sequence + 1:
                        self.estimated_lost += sequence - self.last_sequence - 1
                    if self.last_client_time is not None and client_time >= self.last_client_time:
                        interval = client_time - self.last_client_time
                        self.interval_count += 1
                        delta = interval - self.interval_mean_ms
                        self.interval_mean_ms += delta / self.interval_count
                        self.interval_m2 += delta * (interval - self.interval_mean_ms)
            if self.last_sequence is None or sequence > self.last_sequence:
                self.last_sequence = sequence
                self.last_client_time = client_time
            self.received_samples += 1
            if sample.get("head") is None:
                self.head_invalid += 1
            left = sample.get("left")
            right = sample.get("right")
            if not isinstance(left, dict) or not (left.get("grip") or left.get("ray")):
                self.left_invalid += 1
            if not isinstance(right, dict) or not (right.get("grip") or right.get("ray")):
                self.right_invalid += 1
        if isinstance(client_metrics, dict):
            rtt = client_metrics.get("lastRttMs")
            if finite_number(rtt) and 0 <= rtt <= 60000:
                self.recent_rtt_ms.append(float(rtt))
            offset = client_metrics.get("clockOffsetMs")
            if finite_number(offset) and abs(offset) <= 86400000:
                self.recent_clock_offset_ms.append(float(offset))

    def snapshot(self, now):
        age_ms = max(0.0, (now - self.last_received) * 1000.0)
        jitter_ms = 0.0
        if self.interval_count:
            jitter_ms = math.sqrt(max(0.0, self.interval_m2 / self.interval_count))
        total_expected = self.received_samples + self.estimated_lost
        return {
            "sessionId": self.session_id,
            "linkState": "CONNECTED" if age_ms <= STREAM_TIMEOUT_SECONDS * 1000 else "DISCONNECTED",
            "safetyState": "DISARMED",
            "lastSampleAgeMs": round(age_ms, 1),
            "receivedSamples": self.received_samples,
            "estimatedLost": self.estimated_lost,
            "lossPercent": round(100 * self.estimated_lost / total_expected, 3) if total_expected else 0.0,
            "duplicates": self.duplicates,
            "outOfOrder": self.out_of_order,
            "sampleRateHz": round(1000 / self.interval_mean_ms, 1) if self.interval_mean_ms > 0 else 0.0,
            "sampleJitterMs": round(jitter_ms, 3),
            "recentRttMs": round(sum(self.recent_rtt_ms) / len(self.recent_rtt_ms), 1) if self.recent_rtt_ms else None,
            "clockOffsetMs": round(sum(self.recent_clock_offset_ms) / len(self.recent_clock_offset_ms), 1) if self.recent_clock_offset_ms else None,
            "invalidTracking": {
                "head": self.head_invalid,
                "left": self.left_invalid,
                "right": self.right_invalid,
            },
        }


class SessionRegistry:
    def __init__(self):
        self.lock = threading.Lock()
        self.active = None

    def accept(self, session_id, samples, client_metrics, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            if (self.active is not None and self.active.session_id != session_id and
                    now - self.active.last_received <= STREAM_TIMEOUT_SECONDS):
                raise RuntimeError("another Quest session is active")
            if self.active is None or self.active.session_id != session_id:
                self.active = SessionStats(session_id, now, now)
            self.active.observe(samples, now, client_metrics)
            return self.active.snapshot(now)

    def status(self, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            if self.active is None:
                return {
                    "sessionId": None,
                    "linkState": "DISCONNECTED",
                    "safetyState": "DISARMED",
                }
            return self.active.snapshot(now)


class QuestHandler(SimpleHTTPRequestHandler):
    server_version = "G1QuestRemote/0.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Permissions-Policy", "xr-spatial-tracking=(self)")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:",
        )
        super().end_headers()

    def send_json(self, status, payload):
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/status":
            supervisor = read_supervisor_status()
            self.send_json(HTTPStatus.OK, {
                "ok": True,
                "mode": "READ_ONLY",
                "serverTimeMs": round(time.time() * 1000, 3),
                "streamTimeoutMs": round(STREAM_TIMEOUT_SECONDS * 1000),
                "supervisor": supervisor,
                **self.server.registry.status(),
            })
            return
        super().do_GET()

    def do_POST(self):
        if self.path != "/api/samples":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        server_received_epoch_ms = time.time() * 1000

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        if length <= 0 or length > MAX_BODY_BYTES:
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return

        try:
            payload = json.loads(self.rfile.read(length))
            session, samples = validate_payload(payload)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return

        try:
            metrics = self.server.registry.accept(
                session, samples, payload.get("clientMetrics"))
        except RuntimeError as exc:
            self.send_json(HTTPStatus.CONFLICT, {"ok": False, "error": str(exc)})
            return

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        record = {
            "kind": "samples",
            "receivedAt": datetime.now(timezone.utc).isoformat(),
            "receivedMonotonicMs": round(time.monotonic() * 1000, 3),
            "remote": self.client_address[0],
            "serverMetrics": metrics,
            **payload,
        }
        log_path = LOG_DIR / f"quest-{session}.ndjson"
        with log_lock, log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
        send_safety_datagram(session, samples[-1])
        self.send_json(HTTPStatus.OK, {
            "ok": True,
            "accepted": len(samples),
            "serverReceivedTimeMs": round(server_received_epoch_ms, 3),
            "serverSentTimeMs": round(time.time() * 1000, 3),
            "supervisor": read_supervisor_status(),
            **metrics,
        })

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {self.address_string()} {fmt % args}")


def main():
    parser = argparse.ArgumentParser(description="Serve the G1 Quest WebXR probe over HTTPS")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--ip", default=local_ip(), help="LAN IP included in the TLS certificate")
    args = parser.parse_args()

    try:
        bind_ip = ipaddress.ip_address(args.ip)
    except ValueError:
        parser.error("--ip must be a numeric IPv4 address assigned to the Quest-side interface")
    if bind_ip.version != 4 or bind_ip.is_unspecified:
        parser.error("--ip must be a specific IPv4 address")
    if bind_ip in ipaddress.ip_network("192.168.123.0/24"):
        parser.error("refusing the G1 internal network; use the PC2 Quest-side IP")

    cert, key = ensure_certificate(args.ip)
    bind_address = args.ip
    server = ThreadingHTTPServer((bind_address, args.port), QuestHandler)
    server.registry = SessionRegistry()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=cert, keyfile=key)
    server.socket = context.wrap_socket(server.socket, server_side=True)

    print("G1 Quest Remote — READ ONLY")
    print(f"Quest URL: https://{args.ip}:{args.port}")
    print(f"Listening only on: {bind_address}:{args.port}")
    print(f"Telemetry logs: {LOG_DIR}")
    print("Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
