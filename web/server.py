#!/usr/bin/env python3
"""Small HTTPS server and read-only WebXR telemetry receiver.

This intentionally has no robot, DDS, or command capabilities.  It is the
Phase 2 transport probe: serve the Quest UI and record incoming poses.
"""

import argparse
import json
import socket
import ssl
import subprocess
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = WEB_ROOT.parent
LOG_DIR = PROJECT_ROOT / "logs"
CERT_DIR = PROJECT_ROOT / ".cert"
MAX_BODY_BYTES = 256 * 1024
log_lock = threading.Lock()


def local_ip():
    """Return the address macOS would use for a normal LAN connection."""
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


class QuestHandler(SimpleHTTPRequestHandler):
    server_version = "G1QuestRemote/0.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
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
            self.send_json(HTTPStatus.OK, {
                "ok": True,
                "mode": "READ_ONLY",
                "serverTime": time.time(),
            })
            return
        super().do_GET()

    def do_POST(self):
        if self.path != "/api/samples":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

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
            if not isinstance(payload, dict) or not isinstance(payload.get("samples"), list):
                raise ValueError("expected an object containing samples[]")
            if len(payload["samples"]) > 120:
                raise ValueError("too many samples")
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        session = str(payload.get("sessionId", "unknown"))[:80]
        safe_session = "".join(c for c in session if c.isalnum() or c in "-_") or "unknown"
        record = {
            "receivedAt": datetime.now(timezone.utc).isoformat(),
            "remote": self.client_address[0],
            **payload,
        }
        log_path = LOG_DIR / f"quest-{safe_session}.ndjson"
        with log_lock, log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
        self.send_json(HTTPStatus.OK, {"ok": True, "accepted": len(payload["samples"])})

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {self.address_string()} {fmt % args}")


def main():
    parser = argparse.ArgumentParser(description="Serve the G1 Quest WebXR probe over HTTPS")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--ip", default=local_ip(), help="LAN IP included in the TLS certificate")
    args = parser.parse_args()

    cert, key = ensure_certificate(args.ip)
    server = ThreadingHTTPServer((args.host, args.port), QuestHandler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=cert, keyfile=key)
    server.socket = context.wrap_socket(server.socket, server_side=True)

    print("G1 Quest Remote — READ ONLY")
    print(f"Quest URL: https://{args.ip}:{args.port}")
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
