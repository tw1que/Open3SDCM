"""HTTP and binary STL tests, with the native converter mocked."""

import http.client
import io
import zipfile
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


    @staticmethod
    def batch_body(items):
        manifest = json.dumps([{"name": name, "size": len(data)} for name, data in items]).encode("utf-8")
        return struct.pack(">I", len(manifest)) + manifest + b"".join(data for _, data in items)

    def test_batch_two_good_files_returns_one_zip(self):
        good_stl = b"\0" * 80 + struct.pack("<I", 1) + b"\0" * 50
        seen = []

        def convert(src, target):
            seen.append(src.read_bytes())
            target.write_bytes(good_stl)
            return 1

        body = self.batch_body([("first.dcm", b"AAA"), ("second.dcm", b"BBB")])
        with patch("web.app.convert_dcm_to_stl", side_effect=convert):
            code, headers, data = self.request("POST", "/convert-batch", body)
        self.assertEqual(code, 200)
        self.assertEqual(headers["Content-Type"], "application/zip")
        self.assertEqual(headers["X-Converted-Count"], "2")
        self.assertEqual(headers["X-Failed-Count"], "0")
        self.assertEqual(seen, [b"AAA", b"BBB"])
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(sorted(archive.namelist()), ["first.stl", "second.stl"])
            self.assertEqual(archive.read("first.stl"), good_stl)

    def test_batch_failure_keeps_successful_outputs_and_report(self):
        good_stl = b"\0" * 80 + struct.pack("<I", 1) + b"\0" * 50

        def convert(src, target):
            if src.read_bytes() == b"BAD":
                raise ValueError("invalid dcm")
            target.write_bytes(good_stl)
            return 1

        body = self.batch_body([("good.dcm", b"OK"), ("bad.dcm", b"BAD")])
        with patch("web.app.convert_dcm_to_stl", side_effect=convert):
            code, headers, data = self.request("POST", "/convert-batch", body)
        self.assertEqual(code, 200)
        self.assertEqual(headers["X-Converted-Count"], "1")
        self.assertEqual(headers["X-Failed-Count"], "1")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(sorted(archive.namelist()), ["conversie-fouten.txt", "good.stl"])
            self.assertIn("bad.dcm", archive.read("conversie-fouten.txt").decode())

    def test_batch_duplicate_names_get_unique_entries(self):
        good_stl = b"\0" * 80 + struct.pack("<I", 1) + b"\0" * 50
        def convert(_, target):
            target.write_bytes(good_stl)
            return 1
        body = self.batch_body([("scan.dcm", b"A"), ("SCAN.dcm", b"B")])
        with patch("web.app.convert_dcm_to_stl", side_effect=convert):
            code, _, data = self.request("POST", "/convert-batch", body)
        self.assertEqual(code, 200)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(sorted(archive.namelist()), ["SCAN_2.stl", "scan.stl"])

    def test_batch_all_fail_returns_error(self):
        body = self.batch_body([("one.dcm", b"A"), ("two.dcm", b"B")])
        with patch("web.app.convert_dcm_to_stl", side_effect=ValueError("bad")):
            code, _, data = self.request("POST", "/convert-batch", body)
        self.assertEqual(code, 422)
        self.assertIn("Geen van de bestanden", json.loads(data)["error"])

    def test_batch_mismatch_length_rejected(self):
        body = self.batch_body([("one.dcm", b"A"), ("two.dcm", b"B")]) + b"X"
        code, _, _ = self.request("POST", "/convert-batch", body)
        self.assertEqual(code, 400)

    def test_batch_truncated_body_rejected(self):
        body = self.batch_body([("one.dcm", b"A"), ("two.dcm", b"B")])[:-1]
        code, _, _ = self.request("POST", "/convert-batch", body)
        self.assertEqual(code, 400)

    def test_batch_rejects_directory_names(self):
        body = self.batch_body([("../one.dcm", b"A"), ("two.dcm", b"B")])
        code, _, _ = self.request("POST", "/convert-batch", body)
        self.assertEqual(code, 400)

    def test_batch_rejects_more_than_20(self):
        body = self.batch_body([(f"{i}.dcm", b"A") for i in range(21)])
        code, _, _ = self.request("POST", "/convert-batch", body)
        self.assertEqual(code, 400)


if __name__ == "__main__":
    unittest.main()
