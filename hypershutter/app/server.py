"""Local HTTP server for the app window: the UI files, cached frames and the JSON API.

Bound to 127.0.0.1 only. The API and the frame files need a per-run random token, and the Host
header must be this server, so other pages in a browser cannot call it. Frames are served only
from Application Support, never from an event folder.
"""

from __future__ import annotations

import json
import mimetypes
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from hypershutter.core import config

UI_DIR = config.REPO_ROOT / "ui"
MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


class AppServer:
    def __init__(self, port: int = 0):
        self.token = secrets.token_urlsafe(24)
        self.bridge = None                       # set by main before requests arrive
        self.media_root = config.app_support_dir()
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):      # quiet: requests carry frame paths
                pass

            def _host_ok(self) -> bool:
                return self.headers.get("Host", "") in (f"127.0.0.1:{server.port}", f"localhost:{server.port}")

            def _send(self, code: int, body: bytes, ctype: str, cache: bool = False) -> None:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if not self._host_ok():
                    return self._send(403, b"forbidden", "text/plain")
                path = unquote(urlsplit(self.path).path)
                if path in ("/", "/index.html"):
                    path = "/ui/index.html"
                if path.startswith("/ui/"):
                    f = UI_DIR / path[4:]
                    if _inside(f, UI_DIR) and f.is_file():
                        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
                            ctype += "; charset=utf-8"
                        return self._send(200, f.read_bytes(), ctype)
                    return self._send(404, b"not found", "text/plain")
                if path.startswith("/media/"):
                    _, _, token, rel = path.split("/", 3) if path.count("/") >= 3 else ("", "", "", "")
                    f = server.media_root / rel
                    if (secrets.compare_digest(token, server.token) and f.suffix.lower() in MEDIA_TYPES
                            and _inside(f, server.media_root) and f.is_file()):
                        return self._send(200, f.read_bytes(), MEDIA_TYPES[f.suffix.lower()], cache=True)
                    return self._send(404, b"not found", "text/plain")
                return self._send(404, b"not found", "text/plain")

            def do_POST(self):
                path = urlsplit(self.path).path
                if (not self._host_ok() or not path.startswith("/api/")
                        or not secrets.compare_digest(self.headers.get("X-HS-Token", ""), server.token)):
                    return self._send(403, b"forbidden", "text/plain")
                name = path[5:]
                fn = getattr(server.bridge, name, None) if not name.startswith("_") else None
                if not callable(fn):
                    return self._send(404, b"no such call", "text/plain")
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    args = json.loads(self.rfile.read(length) or b"{}") if length else {}
                    data = {"ok": True, "data": fn(**args)}
                except Exception as e:                       # shown to the user by the UI
                    data = {"ok": False, "error": str(e) or type(e).__name__}
                self._send(200, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?t={self.token}"

    def media_url(self, path: str) -> str:
        rel = Path(path).resolve().relative_to(self.media_root.resolve())
        return f"/media/{self.token}/{quote(str(rel))}"

    def start(self) -> None:
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self) -> None:
        self.httpd.shutdown()
