"""Project asset storage tests: uploads, collision-safe names, and manifests.

Storage functions run against a real temporary project directory, and upload
endpoint tests go through `http.server` over a loopback socket — no filesystem
or handler mocks.
"""

import hashlib
import json
import shutil
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

from prompt_to_shot import projects
from prompt_to_shot.renderers import AssetPathError
from prompt_to_shot.server import make_server

MEDIA_NAMES = (
    "clip.mp4",
    "clip.mov",
    "clip.webm",
    "clip.mkv",
    "frame.png",
    "frame.jpg",
    "frame.jpeg",
    "logo.svg",
    "scene.blend",
    "audio.wav",
    "voice.mp3",
)


class ProjectStorageTests(unittest.TestCase):
    def setUp(self):
        root = Path(tempfile.mkdtemp(prefix="prompt-to-shot-projects-")).resolve()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        self.root = root

    def test_accepts_every_allowlisted_media_extension(self):
        for name in MEDIA_NAMES:
            with self.subTest(name=name):
                relative, entry = projects.store_upload(self.root, name, b"bytes")

                self.assertEqual(relative, f"assets/{name}")
                self.assertTrue((self.root / relative).is_file())
                self.assertEqual(entry["filename"], name)

    def test_extension_check_is_case_insensitive_and_preserves_case(self):
        relative, entry = projects.store_upload(self.root, "Logo.SVG", b"<svg/>")

        self.assertEqual(relative, "assets/Logo.SVG")
        self.assertEqual(entry["filename"], "Logo.SVG")

    def test_rejects_disallowed_extensions(self):
        for name in ("notes.txt", "archive.gz", "payload.exe", "no_extension", ".mp4"):
            with self.subTest(name=name):
                with self.assertRaises(projects.UnsupportedExtensionError):
                    projects.store_upload(self.root, name, b"bytes")
        self.assertFalse((self.root / "assets").exists())

    def test_rejects_unsafe_filenames(self):
        for name in (
            "",
            "   ",
            ".",
            "..",
            "a/b.mp4",
            "a\\b.mp4",
            "../escape.mp4",
            "/abs.mp4",
            "C:drive.mp4",
            "C:\\abs.mp4",
            "nul\x00.mp4",
        ):
            with self.subTest(name=name):
                with self.assertRaises(projects.InvalidFilenameError):
                    projects.store_upload(self.root, name, b"bytes")
        self.assertFalse((self.root / "assets").exists())

    def test_rejects_control_characters_in_filenames(self):
        for name in (
            "bad\nname.mp4",
            "bad\tname.mp4",
            "bad\rname.mp4",
            "\x01clip.mp4",
            "clip\x1f.mp4",
        ):
            with self.subTest(name=name):
                with self.assertRaises(projects.InvalidFilenameError):
                    projects.store_upload(self.root, name, b"bytes")
        self.assertFalse((self.root / "assets").exists())

    def test_upload_content_is_stored_byte_identical(self):
        content = bytes(range(256)) * 3

        relative, entry = projects.store_upload(self.root, "raw.mp3", content)

        self.assertEqual((self.root / relative).read_bytes(), content)
        self.assertEqual(entry["sha256"], hashlib.sha256(content).hexdigest())
        self.assertEqual(entry["bytes"], len(content))

    def test_manifest_entry_records_filename_original_hash_and_bytes(self):
        _, entry = projects.store_upload(self.root, "logo.svg", b"<svg/>")

        self.assertEqual(
            entry,
            {
                "filename": "logo.svg",
                "original_name": "logo.svg",
                "sha256": hashlib.sha256(b"<svg/>").hexdigest(),
                "bytes": 6,
            },
        )

    def test_collision_safe_naming_increments_and_keeps_the_extension(self):
        (self.root / "assets").mkdir()
        (self.root / "assets" / "house_leak.mp4").write_bytes(b"original")

        first, _ = projects.store_upload(self.root, "house_leak.mp4", b"second")
        second, _ = projects.store_upload(self.root, "house_leak.mp4", b"third")

        self.assertEqual(first, "assets/house_leak-2.mp4")
        self.assertEqual(second, "assets/house_leak-3.mp4")
        self.assertEqual(
            (self.root / "assets" / "house_leak.mp4").read_bytes(), b"original"
        )

    def test_collision_naming_preserves_the_original_suffix_casing(self):
        (self.root / "assets").mkdir()
        (self.root / "assets" / "clip.MP4").write_bytes(b"first")

        relative, _ = projects.store_upload(self.root, "clip.MP4", b"second")

        self.assertEqual(relative, "assets/clip-2.MP4")

    def test_second_upload_preserves_the_first_manifest_entry(self):
        _, first = projects.store_upload(self.root, "a.mp4", b"aaa")
        _, second = projects.store_upload(self.root, "b.png", b"bbb")

        self.assertEqual(projects.read_manifest(self.root)["assets"], [first, second])

    def test_manifest_file_uses_the_canonical_json_convention(self):
        projects.store_upload(self.root, "a.mp4", b"aaa")

        text = (self.root / "assets" / "manifest.json").read_text(encoding="utf-8")
        manifest = json.loads(text)
        expected = (
            json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        )

        self.assertEqual(text, expected)

    def test_read_manifest_without_a_manifest_returns_an_empty_one(self):
        self.assertEqual(projects.read_manifest(self.root), {"assets": []})

    def test_corrupt_manifest_raises_a_named_error(self):
        (self.root / "assets").mkdir()
        (self.root / "assets" / "manifest.json").write_text(
            "{not json", encoding="utf-8"
        )

        with self.assertRaises(projects.ManifestError):
            projects.read_manifest(self.root)

    def test_upload_over_the_limit_is_rejected_without_writing(self):
        with self.assertRaises(projects.UploadTooLargeError):
            projects.store_upload(self.root, "a.mp4", b"abcde", max_bytes=4)

        self.assertFalse((self.root / "assets").exists())

    def test_upload_exactly_at_the_limit_is_accepted(self):
        relative, _ = projects.store_upload(self.root, "a.mp4", b"abcd", max_bytes=4)

        self.assertEqual(relative, "assets/a.mp4")

    def test_failed_upload_leaves_no_manifest_entry(self):
        with self.assertRaises(projects.UnsupportedExtensionError):
            projects.store_upload(self.root, "a.txt", b"x")

        self.assertEqual(projects.read_manifest(self.root), {"assets": []})

    def test_unreadable_manifest_fails_the_upload_without_writing_the_asset(self):
        (self.root / "assets").mkdir()
        (self.root / "assets" / "manifest.json").write_text(
            "{not json", encoding="utf-8"
        )

        with self.assertRaises(projects.ManifestError):
            projects.store_upload(self.root, "a.mp4", b"bytes")

        self.assertEqual(
            [path.name for path in (self.root / "assets").iterdir()],
            ["manifest.json"],
        )

    def test_unwritable_project_raises_a_named_storage_error(self):
        (self.root / "assets").mkdir()
        (self.root / "assets").chmod(0o555)
        self.addCleanup((self.root / "assets").chmod, 0o755)

        with self.assertRaises(projects.ProjectStorageError) as raised:
            projects.store_upload(self.root, "a.mp4", b"bytes")

        self.assertIn("a.mp4", str(raised.exception))

    def test_concurrent_uploads_keep_every_entry_and_a_distinct_name(self):
        uploaders = 8
        start = threading.Barrier(uploaders)
        results = []
        errors = []

        def upload():
            try:
                start.wait(timeout=10)
                results.append(projects.store_upload(self.root, "race.mp4", b"race"))
            except Exception as error:  # surfaced below, never swallowed
                errors.append(error)

        threads = [threading.Thread(target=upload) for _ in range(uploaders)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(errors, [])
        names = sorted(entry["filename"] for _, entry in results)
        self.assertEqual(len(set(names)), uploaders)
        self.assertEqual(
            names,
            sorted(
                entry["filename"]
                for entry in projects.read_manifest(self.root)["assets"]
            ),
        )
        for name in names:
            self.assertTrue((self.root / "assets" / name).is_file())

    def test_manifest_reads_never_observe_a_partial_write(self):
        uploaders = 8
        start = threading.Barrier(uploaders)
        stop = threading.Event()
        torn_reads = []

        def read_manifest_until_stopped():
            path = self.root / "assets" / "manifest.json"
            while not stop.is_set():
                try:
                    text = path.read_text(encoding="utf-8")
                except FileNotFoundError:
                    continue
                try:
                    json.loads(text)
                except ValueError:
                    torn_reads.append(text)

        reader = threading.Thread(target=read_manifest_until_stopped, daemon=True)
        reader.start()

        def upload():
            start.wait(timeout=10)
            projects.store_upload(self.root, "race.mp4", b"race")

        threads = [threading.Thread(target=upload) for _ in range(uploaders)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        stop.set()
        reader.join(timeout=10)

        self.assertEqual(torn_reads, [])

    def test_assets_symlink_escaping_the_root_is_rejected(self):
        outside = Path(tempfile.mkdtemp(prefix="prompt-to-shot-outside-")).resolve()
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        (self.root / "assets").symlink_to(outside)

        with self.assertRaises(AssetPathError):
            projects.store_upload(self.root, "a.mp4", b"x")


class UploadApiTests(unittest.TestCase):
    def setUp(self):
        root = Path(tempfile.mkdtemp(prefix="prompt-to-shot-uploads-")).resolve()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        self.project_root = root
        server = make_server("127.0.0.1", 0, project_root=root)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self._stop, server, thread)
        self.base_url = f"http://127.0.0.1:{server.server_port}"

    @staticmethod
    def _stop(server, thread):
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    def request(self, path, *, method="GET", data=None):
        request = urllib.request.Request(self.base_url + path, data=data, method=method)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, dict(response.headers.items()), response.read()
        except urllib.error.HTTPError as error:
            with error:
                return error.code, dict(error.headers.items()), error.read()

    def upload(self, name, data=b"x"):
        quoted = urllib.parse.quote(name, safe="")
        return self.request(f"/api/upload?filename={quoted}", method="POST", data=data)

    def raw_request(self, method, path, *, headers=None, body=b""):
        """Send a hand-built HTTP/1.0 request so malformed framing is possible."""
        lines = [f"{method} {path} HTTP/1.0", "Host: 127.0.0.1"]
        lines.extend(f"{name}: {value}" for name, value in (headers or {}).items())
        payload = ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8") + body
        port = urllib.parse.urlsplit(self.base_url).port
        with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
            connection.sendall(payload)
            connection.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
        head, _, body_bytes = b"".join(chunks).partition(b"\r\n\r\n")
        status_line = head.split(b"\r\n", 1)[0]
        return int(status_line.split()[1]), body_bytes

    def test_upload_stores_the_file_and_returns_path_and_entry(self):
        status, headers, body = self.upload("logo.svg", b"<svg/>")

        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("application/json"))
        payload = json.loads(body)
        self.assertEqual(payload["path"], "assets/logo.svg")
        self.assertEqual(payload["entry"]["filename"], "logo.svg")
        self.assertEqual(payload["entry"]["original_name"], "logo.svg")
        self.assertEqual(payload["entry"]["sha256"], hashlib.sha256(b"<svg/>").hexdigest())
        self.assertEqual(payload["entry"]["bytes"], 6)
        self.assertEqual((self.project_root / "assets" / "logo.svg").read_bytes(), b"<svg/>")

    def test_upload_manifest_persists_across_requests(self):
        self.upload("a.mp4", b"aaa")

        status, _, _ = self.upload("b.png", b"bbb")

        self.assertEqual(status, 200)
        manifest = json.loads(
            (self.project_root / "assets" / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            [entry["filename"] for entry in manifest["assets"]], ["a.mp4", "b.png"]
        )

    def test_upload_collision_gets_a_numbered_name(self):
        self.upload("a.mp4", b"one")

        status, _, body = self.upload("a.mp4", b"two")

        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["path"], "assets/a-2.mp4")
        self.assertEqual((self.project_root / "assets" / "a.mp4").read_bytes(), b"one")

    def test_upload_without_a_filename_returns_400(self):
        status, _, body = self.request("/api/upload", method="POST", data=b"x")

        self.assertEqual(status, 400)
        self.assertIn("filename", json.loads(body)["error"])

    def test_upload_with_an_empty_filename_returns_400(self):
        status, _, _ = self.upload("")

        self.assertEqual(status, 400)

    def test_upload_with_a_duplicate_filename_parameter_returns_400(self):
        status, _, body = self.request(
            "/api/upload?filename=a.mp4&filename=b.mp4", method="POST", data=b"x"
        )

        self.assertEqual(status, 400)
        self.assertIn("filename", json.loads(body)["error"])
        self.assertFalse((self.project_root / "assets").exists())

    def test_upload_with_unsafe_filenames_returns_400(self):
        for name in ("../escape.mp4", "a/b.mp4", "..", "bad\nname.mp4", "bad\tname.mp4"):
            with self.subTest(name=name):
                status, _, body = self.upload(name)

                self.assertEqual(status, 400)
                self.assertIn("filename", json.loads(body)["error"])

    def test_upload_with_a_disallowed_extension_returns_415(self):
        status, _, body = self.upload("notes.txt", b"x")

        self.assertEqual(status, 415)
        self.assertIn("notes.txt", json.loads(body)["error"])

    def test_upload_with_an_empty_body_returns_400(self):
        status, _, body = self.upload("a.mp4", b"")

        self.assertEqual(status, 400)

    def test_upload_with_an_invalid_content_length_returns_400(self):
        status, body = self.raw_request(
            "POST",
            "/api/upload?filename=a.mp4",
            headers={"Content-Length": "abc"},
            body=b"x",
        )

        self.assertEqual(status, 400)
        self.assertIn("Content-Length", json.loads(body)["error"])
        self.assertFalse((self.project_root / "assets").exists())

    def test_upload_with_a_short_body_returns_400(self):
        status, body = self.raw_request(
            "POST",
            "/api/upload?filename=a.mp4",
            headers={"Content-Length": "10"},
            body=b"four",
        )

        self.assertEqual(status, 400)
        self.assertIn("Content-Length", json.loads(body)["error"])
        self.assertFalse((self.project_root / "assets").exists())

    def test_upload_into_an_unwritable_project_returns_500(self):
        self.upload("a.mp4", b"one")
        (self.project_root / "assets").chmod(0o555)
        self.addCleanup((self.project_root / "assets").chmod, 0o755)

        status, _, body = self.upload("b.png", b"two")

        self.assertEqual(status, 500)
        self.assertIn("b.png", json.loads(body)["error"])

    def test_upload_over_the_limit_returns_413_without_writing(self):
        with mock.patch.object(projects, "MAX_UPLOAD_BYTES", 4):
            status, _, body = self.upload("a.mp4", b"toolong")

        self.assertEqual(status, 413)
        self.assertIn("limit", json.loads(body)["error"])
        self.assertFalse((self.project_root / "assets").exists())

    def test_upload_through_an_escaping_assets_symlink_returns_400(self):
        outside = Path(tempfile.mkdtemp(prefix="prompt-to-shot-outside-")).resolve()
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        (self.project_root / "assets").symlink_to(outside)

        status, _, body = self.upload("a.mp4", b"x")

        self.assertEqual(status, 400)
        self.assertIn("project root", json.loads(body)["error"])

    def test_get_upload_returns_405(self):
        status, _, _ = self.request("/api/upload")

        self.assertEqual(status, 405)


if __name__ == "__main__":
    unittest.main()
