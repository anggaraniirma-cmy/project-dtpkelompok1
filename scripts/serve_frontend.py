"""Server statis kecil untuk kedua frontend (tanpa dependency tambahan).

Admin   -> http://localhost:3000
Visitor -> http://localhost:8080

Bila port sudah dipakai (mis. dev server lain), server mencoba port
berikutnya dan mencetak URL yang benar-benar dipakai. File yang diminta
dibatasi di dalam folder frontend (mencegah path traversal).
"""
from __future__ import annotations

import argparse
import http.server
import json
import mimetypes
import os
import socket
import socketserver
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
FRONTENDS = {
    "admin": PROJECT_DIR / "frontend" / "admin",
    "visitor": PROJECT_DIR / "frontend" / "visitor",
}
DEFAULT_PORTS = {"admin": 3000, "visitor": 8080}

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")


class Handler(http.server.SimpleHTTPRequestHandler):
    root: Path = PROJECT_DIR
    api_url: str = "http://localhost:8000"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(self.root), **kwargs)

    def log_message(self, fmt, *args):  # ringkas
        sys.stderr.write("  %s - %s\n" % (self.address_string(), fmt % args))

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/config.js", "/assets/js/config.js"):
            body = f"window.SKOMDA_API = {json.dumps(self.api_url)};\n".encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        # SPA-ish: tanpa ekstensi -> index.html
        if "." not in Path(path).name:
            self.path = "/index.html"
        super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    # Di Windows SO_REUSEADDR berperilaku seperti SO_REUSEPORT: port yang SUDAH
    # dipakai proses lain bisa "dibajak" secara diam-diam. Karena itu jangan
    # dipakai; kelayakan port diperiksa sendiri di pick_port().
    allow_reuse_address = False


def port_free(port: int) -> bool:
    """Port benar-benar bebas: tidak ada yang listen & bisa di-bind."""
    # 1) Ada proses yang menerima koneksi di port ini? -> terpakai.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.25)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            return False
    # 2) Bisa di-bind tanpa SO_REUSEADDR? -> biasanya bebas.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def pick_port(preferred: int, tries: int = 12) -> int:
    if port_free(preferred):
        return preferred
    for p in range(preferred + 1, preferred + tries):
        if port_free(p):
            return p
    raise SystemExit(f"Tidak ada port bebas di sekitar {preferred}")


def serve(which: str, port: int | None = None, api_url: str = "http://localhost:8000") -> int:
    root = FRONTENDS[which]
    if not (root / "index.html").exists():
        raise SystemExit(f"index.html tidak ditemukan di {root}")

    wanted = port or DEFAULT_PORTS[which]
    actual = pick_port(wanted)
    Handler.root = root
    Handler.api_url = api_url

    srv = ThreadingServer(("127.0.0.1", actual), Handler)
    label = "Admin Panel" if which == "admin" else "Visitor/Game Panel"
    print(f"  {label:<20} -> http://localhost:{actual}  (API {api_url})" +
          (f"  [port {wanted} terpakai]" if actual != wanted else ""), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print(f"  {label} dihentikan.")
    finally:
        srv.server_close()
    return actual


def main() -> None:
    ap = argparse.ArgumentParser(description="Server statis frontend SKOMDA Gesture Quiz")
    ap.add_argument("which", choices=["admin", "visitor"])
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--api", default=os.getenv("SKOMDA_API_URL", "http://localhost:8000"))
    args = ap.parse_args()
    serve(args.which, args.port, args.api)


if __name__ == "__main__":
    main()
