"""HTTP smoke tests that do not require a compiled Open3SDCMCLI."""

from __future__ import annotations

import http.client
from pathlib import Path
import struct
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

from web.app import Handler


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Handler.cli = "dummy-cli"
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        result = (response.status, dict(response.getheaders()), response.read())
        conn.close()
        return result

    def test_index(self):
        code, headers, content = self.request("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn(b"DCM", content)
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_reject_wrong_file(self):
        code, _, _ = self.request("POST", "/convert", b"data", {"X-Filename": "scan.txt"})
        self.assertEqual(code, 400)

    def test_reject_path_in_filename(self):
        code, _, _ = self.request("POST", "/convert", b"data", {"X-Filename": "..%2Fscan.dcm"})
        self.assertEqual(code, 400)

    def test_reject_oversized_file(self):
        code, _, _ = self.request("POST", "/convert", b"", {"X-Filename": "scan.dcm", "Content-Length": "104857601"})
        self.assertEqual(code, 413)

    def test_success_returns_valid_stl(self):
        stl = b"\0" * 80 + struct.pack("<I", 1) + b"\0" * 50

        def cli_run(command, **_):
            out = Path(command[command.index("-o") + 1]) / "2026-10-30-09-00-00"
            out.mkdir()
            (out / "input.stl").write_bytes(stl)
            self.assertEqual(command[-1], "stl")
            return SimpleNamespace(returncode=0)

        with patch("web.app.subprocess.run", side_effect=cli_run):
            code, headers, content = self.request("POST", "/convert", b"DCM", {"X-Filename": "scan.dcm"})
        self.assertEqual(code, 200)
        self.assertEqual(content, stl)
        self.assertEqual(headers["X-Triangle-Count"], "1")
        self.assertEqual(headers["Content-Type"], "model/stl")

    def test_false_success_without_stl(self):
        with patch("web.app.subprocess.run", return_value=SimpleNamespace(returncode=0)):
            code, _, content = self.request("POST", "/convert", b"DCM", {"X-Filename": "scan.dcm"})
        self.assertEqual(code, 422)
        self.assertIn(b"geen geldige stl", content.lower())


if __name__ == "__main__":
    unittest.main()
