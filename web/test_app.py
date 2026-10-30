"""HTTP and binary STL tests, with the native converter mocked."""

import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import struct
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

import numpy as np
from web.app import Handler, convert_dcm_to_stl


class BinaryStlTests(unittest.TestCase):
    def test_writer_normals_and_geometry(self):
        mesh = types.SimpleNamespace(
            vertices=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32),
            faces=np.array([[0, 1, 2]], dtype=np.uint64),
        )
        with patch.dict(sys.modules, {"open3sdcm": types.SimpleNamespace(load=lambda _: mesh)}):
            with tempfile.TemporaryDirectory() as root:
                stl = Path(root) / "result.stl"
                count = convert_dcm_to_stl(Path(root) / "example.dcm", stl)
                data = stl.read_bytes()
        self.assertEqual(count, 1)
        self.assertEqual(len(data), 134)
        self.assertEqual(struct.unpack_from('<I', data, 80)[0], 1)
        normal = struct.unpack_from('<3f', data, 84)
        self.assertEqual(normal, (0.0, 0.0, 1.0))
        corners = struct.unpack_from('<9f', data, 96)
        self.assertEqual(corners, (0, 0, 0, 1, 0, 0, 0, 1, 0))

    def test_writer_invalid_indices(self):
        mesh = types.SimpleNamespace(
            vertices=np.array([[0, 0, 0]], dtype=np.float32),
            faces=np.array([[0, 1, 2]], dtype=np.uint64),
        )
        with patch.dict(sys.modules, {"open3sdcm": types.SimpleNamespace(load=lambda _: mesh)}):
            with tempfile.TemporaryDirectory() as root:
                with self.assertRaises(ValueError):
                    convert_dcm_to_stl(Path(root) / "example.dcm", Path(root) / "result.stl")


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
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

        def conversion(src, target):
            self.assertEqual(src.read_bytes(), b"DCM")
            target.write_bytes(stl)
            return 1

        with patch("web.app.convert_dcm_to_stl", side_effect=conversion):
            code, headers, content = self.request("POST", "/convert", b"DCM", {"X-Filename": "scan.dcm"})
        self.assertEqual(code, 200)
        self.assertEqual(content, stl)
        self.assertEqual(headers["X-Triangle-Count"], "1")
        self.assertEqual(headers["Content-Type"], "model/stl")

    def test_failure_returns_422(self):
        with patch("web.app.convert_dcm_to_stl", side_effect=ValueError("bad scan")):
            code, _, content = self.request("POST", "/convert", b"DCM", {"X-Filename": "scan.dcm"})
        self.assertEqual(code, 422)
        self.assertIn("Geen geldige STL", json.loads(content)["error"])


if __name__ == "__main__":
    unittest.main()
