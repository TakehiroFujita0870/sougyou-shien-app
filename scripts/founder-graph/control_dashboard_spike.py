"""Synthetic CTRL-SP-02 proof: a loopback controller outlives its child."""
from __future__ import annotations

import json
import secrets
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class FakeChild:
    """A disposable HTTP child, intentionally unrelated to the Dots runtime."""

    def __init__(self) -> None:
        self.port = _free_port()
        self.process: subprocess.Popen[bytes] | None = None

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self) -> None:
        if not self.running:
            self.process = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "--fake-child", str(self.port)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def stop(self) -> None:
        if self.running:
            assert self.process is not None
            self.process.terminate()
            self.process.wait(timeout=3)
        self.process = None


class Controller:
    def __init__(self) -> None:
        self.child = FakeChild()
        self.csrf = secrets.token_urlsafe(24)
        self.server = None
        self.thread = None
        # Requests select only these functions; no request value becomes a command.
        self.allowed = {
            ("fake-child", "start"): self.child.start,
            ("fake-child", "stop"): self.child.stop,
        }

    def start(self) -> None:
        control = self

        class Handler(BaseHTTPRequestHandler):
            def reply(self, status: int, body: dict[str, object]) -> None:
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                if self.headers.get("Host") != f"127.0.0.1:{control.server.server_port}":
                    self.reply(403, {"error": "invalid host"})
                elif self.path != "/api/status":
                    self.reply(404, {"error": "not found"})
                else:
                    self.reply(200, {"controller": "running", "fake_child": "running" if control.child.running else "stopped", "csrf": control.csrf})

            def do_POST(self) -> None:
                expected_origin = f"http://127.0.0.1:{control.server.server_port}"
                if self.headers.get("Host") != f"127.0.0.1:{control.server.server_port}":
                    self.reply(403, {"error": "invalid host"}); return
                if self.headers.get("Origin") != expected_origin:
                    self.reply(403, {"error": "invalid origin"}); return
                if not secrets.compare_digest(self.headers.get("X-CSRF-Token", ""), control.csrf):
                    self.reply(403, {"error": "invalid csrf"}); return
                parts = self.path.strip("/").split("/")
                key = (parts[2], parts[3]) if len(parts) == 4 and parts[:2] == ["api", "services"] else None
                operation = control.allowed.get(key)
                if operation is None:
                    self.reply(404, {"error": "service or operation not allowed"}); return
                operation()
                self.reply(200, {"accepted": True, "fake_child": "running" if control.child.running else "stopped"})

            def log_message(self, _format: str, *_args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def address(self) -> tuple[str, int]:
        return self.server.server_address

    def close(self) -> None:
        self.child.stop()
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=3)


def _fake_child(port: int) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), BaseHTTPRequestHandler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--fake-child":
        _fake_child(int(sys.argv[2]))
    else:
        raise SystemExit("Run the synthetic tests; this proof is not a product service.")
