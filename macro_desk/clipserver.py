"""Serve a single audio file over HTTP so a Sonos player can fetch it.

Sonos pulls audio from a URL rather than accepting a stream pushed to it, so
the clip has to be reachable from the speaker. This server exposes exactly one
file under an unguessable name and stops when the context exits.
"""

from __future__ import annotations

import secrets
import socket
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def local_ip_for(target: str, port: int = 1400) -> str:
    """The address of the interface this machine would use to reach ``target``."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect((target, port))  # UDP connect sends nothing; it only picks a route
        return s.getsockname()[0]


class ClipServer:
    def __init__(self, path: Path, advertise_host: str, port: int = 0, bind: str = "0.0.0.0"):
        self.path = path
        self.advertise_host = advertise_host
        self.route = f"/{secrets.token_urlsafe(8)}-{path.name}"
        self._server = ThreadingHTTPServer((bind, port), self._handler())
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    @property
    def url(self) -> str:
        return f"http://{self.advertise_host}:{self.port}{self.route}"

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        clip = self

        class Handler(BaseHTTPRequestHandler):
            def _head(self) -> bool:
                if self.path != clip.route or not clip.path.is_file():
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return False
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(clip.path.stat().st_size))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return True

            def do_HEAD(self) -> None:
                self._head()

            def do_GET(self) -> None:
                if self._head():
                    self.wfile.write(clip.path.read_bytes())

            def log_message(self, *args) -> None:
                pass

        return Handler

    def __enter__(self) -> "ClipServer":
        self._thread = threading.Thread(target=self._server.serve_forever, name="clip-server", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()
