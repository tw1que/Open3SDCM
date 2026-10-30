"""Local-only drag-and-drop UI for the existing Open3SDCMCLI converter.

Run from any directory: python web/app.py
Set OPEN3SDCM_CLI to the CLI executable when it is not on PATH.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

MAX_DCM_BYTES = 100 * 1024 * 1024
CONVERT_TIMEOUT = 180
INDEX_HTML = Path(__file__).with_name("index.html")
ROOT = Path(__file__).resolve().parent.parent


def find_cli() -> str | None:
    configured = os.environ.get("OPEN3SDCM_CLI")
    if configured:
        path = Path(configured).expanduser()
        return str(path.resolve()) if path.is_file() else None

    for name in ("Open3SDCMCLI", "Open3SDCMCLI.exe"):
        # Both single-config and multi-config (Windows) CMake builds.
        for candidate in ROOT.glob(f"builds/*/bin/**/{name}"):
            if candidate.is_file():
                return str(candidate.resolve())
        command = shutil.which(name)
        if command:
            return command
    return None


def valid_binary_stl(path: Path) -> bool:
    """The CLI may exit 0 even when no valid mesh was exported."""
    if not path.is_file() or path.stat().st_size < 134:
        return False
    with path.open("rb") as handle:
        handle.seek(80)
        triangles = struct.unpack("<I", handle.read(4))[0]
    return triangles > 0 and path.stat().st_size == 84 + triangles * 50


class Handler(BaseHTTPRequestHandler):
    cli: str = ""
    server_version = "Open3SDCMWeb/1.0"

    def log_message(self, format: str, *args: object) -> None:
        # Upload filenames may contain patient information: no access logs.
        pass

    def send_bytes(self, status: int, content: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def fail(self, status: int, message: str) -> None:
        self.send_bytes(status, json.dumps({"error": message}, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        if self.path not in ("/", "/index.html"):
            self.fail(404, "Pagina niet gevonden.")
            return
        self.send_bytes(200, INDEX_HTML.read_bytes(), "text/html; charset=utf-8")

    def do_POST(self) -> None:
        if self.path != "/convert":
            self.fail(404, "Endpoint niet gevonden.")
            return

        filename = unquote(self.headers.get("X-Filename", ""))
        # Reject path components instead of trusting browser-supplied names.
        if not filename or len(filename) > 200 or "/" in filename or "\\" in filename or not filename.lower().endswith(".dcm"):
            self.fail(400, "Selecteer een geldig .dcm-bestand.")
            return

        try:
            size = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self.fail(411, "Bestandsgrootte ontbreekt.")
            return
        if size < 1 or size > MAX_DCM_BYTES:
            self.fail(413, "Het DCM-bestand moet tussen 1 byte en 100 MB groot zijn.")
            return

        with tempfile.TemporaryDirectory(prefix="open3sdcm-web-") as temp:
            root = Path(temp)
            dcm_path = root / "input.dcm"
            output_dir = root / "output"
            output_dir.mkdir()
            try:
                remaining = size
                with dcm_path.open("wb") as out:
                    while remaining:
                        chunk = self.rfile.read(min(1024 * 1024, remaining))
                        if not chunk:
                            self.fail(400, "Bestand is niet volledig ontvangen.")
                            return
                        out.write(chunk)
                        remaining -= len(chunk)

                result = subprocess.run(
                    [self.cli, "-i", str(dcm_path), "-o", str(output_dir), "-f", "stl"],
                    capture_output=True, text=True, errors="replace", timeout=CONVERT_TIMEOUT,
                )
                results = list(output_dir.rglob("input.stl"))
                stl_path = results[0] if len(results) == 1 else None
                if result.returncode != 0 or stl_path is None or not valid_binary_stl(stl_path):
                    # CLI currently sometimes returns 0 despite failed export.
                    self.fail(422, "Geen geldige STL gegenereerd. Het DCM-bestand kan versleuteld, beschadigd of niet ondersteund zijn.")
                    return

                self.send_response(200)
                self.send_header("Content-Type", "model/stl")
                self.send_header("Content-Length", str(stl_path.stat().st_size))
                self.send_header("Content-Disposition", "attachment; filename=\"converted.stl\"")
                self.send_header("X-Triangle-Count", str((stl_path.stat().st_size - 84) // 50))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                with stl_path.open("rb") as source:
                    shutil.copyfileobj(source, self.wfile, 1024 * 1024)
            except subprocess.TimeoutExpired:
                self.fail(504, "De conversie duurde te lang (meer dan 3 minuten).")
            except OSError:
                self.fail(500, "Er is een fout opgetreden bij het uitvoeren van de converter.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Local Open3SDCM drag-and-drop interface")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    cli = find_cli()
    if not cli:
        parser.error("Open3SDCMCLI niet gevonden. Zet OPEN3SDCM_CLI naar het uitvoerbare bestand of bouw eerst de CLI.")
    Handler.cli = cli
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print(f"Open http://127.0.0.1:{server.server_port} in je browser. Ctrl+C om te stoppen.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
