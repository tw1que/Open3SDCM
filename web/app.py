"""Local DCM-to-STL web interface using the Open3SDCM Python wheel.

Run python web/app.py after pip install open3sdcm==1.1.4.
Or double-click start.bat on Windows to set up and launch.
"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import struct
import tempfile
from urllib.parse import unquote
import webbrowser
import zipfile

MAX_DCM_BYTES = 100 * 1024 * 1024
MAX_BATCH_FILES = 20
MAX_BATCH_BYTES = 500 * 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024
INDEX_HTML = Path(__file__).with_name("index.html")


def convert_dcm_to_stl(source: Path, target: Path) -> int:
    """Decode DCM with published Python bindings; write geometry-only binary STL."""
    import numpy as np
    import open3sdcm

    mesh = open3sdcm.load(source)
    vertices = np.asarray(mesh.vertices, dtype=np.float32)
    faces = np.asarray(mesh.faces)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or len(vertices) == 0:
        raise ValueError("DCM bevat geen geldige vertices")
    if faces.ndim != 2 or faces.shape[1] != 3 or not 0 < len(faces) < 2**32:
        raise ValueError("DCM bevat geen geldige driehoeken")
    if not np.isfinite(vertices).all():
        raise ValueError("DCM bevat niet-eindige coördinaten")
    if not np.issubdtype(faces.dtype, np.integer):
        raise ValueError("DCM heeft ongeldige driehoekindices")

    facet_dtype = np.dtype([
        ("normal", "<f4", (3,)),
        ("corners", "<f4", (3, 3)),
        ("attributes", "<u2"),
    ])
    with target.open("wb") as out:
        out.write(b"Open3SDCM local DCM to STL".ljust(80, b"\0"))
        out.write(struct.pack("<I", len(faces)))
        for offset in range(0, len(faces), 20_000):
            indices = faces[offset:offset + 20_000]
            if (indices < 0).any() or (indices >= len(vertices)).any():
                raise ValueError("DCM bevat driehoekindices buiten het bereik")
            corners = vertices[indices.astype(np.intp)]
            normals = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
            norms = np.linalg.norm(normals, axis=1)
            good = np.isfinite(norms) & (norms > 0)
            normals[good] /= norms[good, None]
            normals[~good] = 0
            facets = np.zeros(len(indices), dtype=facet_dtype)
            facets["normal"] = normals
            facets["corners"] = corners
            out.write(facets.tobytes())
    return len(faces)


class Handler(BaseHTTPRequestHandler):
    server_version = "Open3SDCMWeb/2.0"

    def log_message(self, format: str, *args: object) -> None:
        # Dental file names can identify patients; no access logs.
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
        data = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
        self.send_bytes(status, data, "application/json; charset=utf-8")

    def do_GET(self) -> None:
        if self.path not in ("/", "/index.html"):
            self.fail(404, "Pagina niet gevonden.")
            return
        self.send_bytes(200, INDEX_HTML.read_bytes(), "text/html; charset=utf-8")

    def do_POST(self) -> None:
        if self.path == "/convert-batch":
            self.convert_batch()
            return
        if self.path != "/convert":
            self.fail(404, "Endpoint niet gevonden.")
            return

        filename = unquote(self.headers.get("X-Filename", ""))
        if (not filename or len(filename) > 200 or "/" in filename or "\\" in filename
                or not filename.lower().endswith(".dcm")):
            self.fail(400, "Selecteer een geldig .dcm-bestand.")
            return
        try:
            size = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self.fail(411, "Bestandsgrootte ontbreekt.")
            return
        if not 1 <= size <= MAX_DCM_BYTES:
            self.fail(413, "Het DCM-bestand moet tussen 1 byte en 100 MB groot zijn.")
            return

        with tempfile.TemporaryDirectory(prefix="open3sdcm-web-") as temp:
            source = Path(temp) / "scan.dcm"
            target = Path(temp) / "scan.stl"
            try:
                remaining = size
                with source.open("wb") as out:
                    while remaining:
                        chunk = self.rfile.read(min(1024 * 1024, remaining))
                        if not chunk:
                            self.fail(400, "Bestand is niet volledig ontvangen.")
                            return
                        out.write(chunk)
                        remaining -= len(chunk)

                count = convert_dcm_to_stl(source, target)
                if target.stat().st_size != 84 + 50 * count:
                    raise ValueError("STL export is ongeldig")
                self.send_response(200)
                self.send_header("Content-Type", "model/stl")
                self.send_header("Content-Length", str(target.stat().st_size))
                self.send_header("Content-Disposition", 'attachment; filename="converted.stl"')
                self.send_header("X-Triangle-Count", str(count))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                with target.open("rb") as f:
                    shutil.copyfileobj(f, self.wfile, 1024 * 1024)
            except (OSError, ValueError, RuntimeError, IndexError, OverflowError):
                self.fail(422, "Geen geldige STL gegenereerd. Het DCM-bestand kan versleuteld, beschadigd of niet ondersteund zijn.")


    @staticmethod
    def valid_filename(filename: object) -> bool:
        return (
            isinstance(filename, str)
            and 0 < len(filename) <= 200
            and filename.lower().endswith(".dcm")
            and not any(c in filename for c in ("/", "\\", "\0", "\r", "\n"))
            and not any(ord(c) < 32 for c in filename)
        )

    def convert_batch(self) -> None:
        """Protocol: 4-byte big-endian JSON byte length, UTF-8 manifest, raw files.

        Manifest: [{"name": "scan.dcm", "size": 123}, ...]. The byte sizes
        delimit each file. Content-Length must exactly match the entire body.
        All data stays on the local machine, streamed to temporary files.
        """
        try:
            size = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self.fail(411, "Bestandsgrootte ontbreekt.")
            return
        if not 4 < size <= MAX_BATCH_BYTES + MAX_MANIFEST_BYTES + 4:
            self.fail(413, "De batch is te groot (maximaal 500 MB).")
            return

        header = self.rfile.read(4)
        if len(header) != 4:
            self.fail(400, "Onvolledige batch-header.")
            return
        manifest_size = struct.unpack(">I", header)[0]
        if not 2 <= manifest_size <= MAX_MANIFEST_BYTES or size < manifest_size + 4:
            self.fail(400, "Ongeldig batch-overzicht.")
            return
        try:
            manifest = json.loads(self.rfile.read(manifest_size).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.fail(400, "Ongeldig batch-overzicht.")
            return
        if not isinstance(manifest, list) or not 2 <= len(manifest) <= MAX_BATCH_FILES:
            self.fail(400, "Selecteer 2 tot 20 DCM-bestanden.")
            return
        for item in manifest:
            if (not isinstance(item, dict)
                or not self.valid_filename(item.get("name"))
                or type(item.get("size")) is not int
                or not 1 <= item["size"] <= MAX_DCM_BYTES):
                self.fail(400, "Ongeldige bestandsnaam of bestandsgrootte (maximaal 100 MB per DCM).")
                return
        total = sum(item["size"] for item in manifest)
        if total > MAX_BATCH_BYTES or size != 4 + manifest_size + total:
            self.fail(400, "Bestandsgroottes kloppen niet (maximaal 500 MB totaal).")
            return

        with tempfile.TemporaryDirectory(prefix="open3sdcm-batch-") as temp:
            root = Path(temp)
            zip_path = root / "result.zip"
            success = 0
            errors = []
            used_names = set()
            try:
                with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=2) as archive:
                    for i, item in enumerate(manifest):
                        source = root / f"source-{i}.dcm"
                        target = root / f"output-{i}.stl"
                        remaining = item["size"]
                        with source.open("wb") as out:
                            while remaining:
                                chunk = self.rfile.read(min(1024 * 1024, remaining))
                                if not chunk:
                                    raise EOFError("Batch-upload is onvolledig.")
                                out.write(chunk)
                                remaining -= len(chunk)
                        try:
                            count = convert_dcm_to_stl(source, target)
                            if target.stat().st_size != 84 + 50 * count or count < 1:
                                raise ValueError("STL-export is ongeldig")
                            name = item["name"][:-4] + ".stl"
                            stem = name[:-4]
                            suffix = 2
                            while name.casefold() in used_names:
                                name = f"{stem}_{suffix}.stl"
                                suffix += 1
                            used_names.add(name.casefold())
                            archive.write(target, arcname=name)
                            success += 1
                        except (OSError, ValueError, RuntimeError, IndexError, OverflowError, MemoryError) as error:
                            errors.append(f"{item['name']}: conversie mislukt ({type(error).__name__}); mogelijk versleuteld of niet ondersteund.")
                        finally:
                            source.unlink(missing_ok=True)
                            target.unlink(missing_ok=True)
                    if errors:
                        archive.writestr("conversie-fouten.txt", "\n".join(errors) + "\n")
                if not success:
                    self.fail(422, "Geen van de bestanden kon worden geconverteerd. Mogelijk versleutelde of niet-ondersteunde DCM-bestanden.")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", 'attachment; filename="converted-stl.zip"')
                self.send_header("Content-Length", str(zip_path.stat().st_size))
                self.send_header("X-Converted-Count", str(success))
                self.send_header("X-Failed-Count", str(len(errors)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                with zip_path.open("rb") as downloaded:
                    shutil.copyfileobj(downloaded, self.wfile, 1024 * 1024)
            except EOFError:
                self.fail(400, "Batch-upload is onvolledig.")
            except OSError:
                self.fail(500, "Fout tijdens batchconversie.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Local Open3SDCM drag-and-drop interface")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")
    args = parser.parse_args()
    try:
        import numpy
        import open3sdcm
    except ImportError:
        parser.error("Python-pakket ontbreekt. Voer uit: python -m pip install --only-binary=:all: open3sdcm==1.1.4")

    try:
        with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
            url = f"http://127.0.0.1:{server.server_port}"
            print(f"DCM -> STL draait lokaal op {url}. Druk Ctrl+C om te stoppen.")
            if not args.no_browser:
                webbrowser.open(url)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
    except OSError as error:
        parser.error(f"Kon de lokale webserver niet starten: {error}")


if __name__ == "__main__":
    main()
