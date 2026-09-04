import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ulo_videos.cloud_worker import _caption_text_from_scene, _create_output_asset, _put_blob, _update_job, fallback_health, download_request, queue_message, ffmpeg_command


class CloudWorkerContractTests(unittest.TestCase):
    def test_queue_message_requires_bearer_secret_and_job_id(self):
        self.assertEqual(queue_message(b'{"renderJobId":"rj_123"}', "Bearer secret", "secret"), {"renderJobId": "rj_123"})
        with self.assertRaises(ValueError):
            queue_message(b"{}", "Bearer secret", "secret")
        with self.assertRaises(PermissionError):
            queue_message(b'{"renderJobId":"rj_123"}', "Bearer wrong", "secret")
        for unsafe_id in ("rj_../secret", "rj_..\\secret", "rj_"):
            with self.assertRaises(ValueError):
                queue_message(json.dumps({"renderJobId": unsafe_id}).encode(), "Bearer secret", "secret")

    def test_fallback_health_describes_only_the_stages_it_applies(self):
        self.assertEqual(fallback_health(), {
            "ok": True,
            "mode": "vercel_fallback",
            "capabilities": {"freezeResume": True, "logo": True, "captions": True, "character": False, "sourceAudio": False, "speech": False, "lipSync": False, "characterFormats": []},
        })

    def test_ffmpeg_command_is_deterministic_mp4_output(self):
        command = ffmpeg_command("/tmp/input.mp4", "/tmp/output.mp4", 7.4, 1920, 1080, 30)
        self.assertEqual(command[0], "ffmpeg")
        self.assertTrue(any("trim=end=7.4" in item for item in command))
        self.assertEqual(command[-1], "/tmp/output.mp4")

    def test_ffmpeg_command_composites_logo_and_lower_third_caption(self):
        command = ffmpeg_command(
            "/tmp/input.mp4",
            "/tmp/output.mp4",
            7.4,
            1920,
            1080,
            30,
            logo="/tmp/logo.svg",
            caption_text="Every landlord knows real estate isn't passive.",
            caption_style="lower_third",
        )

        self.assertEqual(command.count("-i"), 2)
        self.assertEqual(command[command.index("-i", command.index("-i") + 1) + 1], "/tmp/logo.svg")
        filters = command[command.index("-filter_complex") + 1]
        self.assertIn("overlay=W-w-48:H-h-48", filters)
        self.assertIn("drawtext=text='Every landlord knows real estate", filters)
        self.assertIn("y=h-th-60", filters)

    def test_ffmpeg_logo_persists_for_the_entire_render(self):
        command = ffmpeg_command(
            "/tmp/input.mp4",
            "/tmp/output.mp4",
            7.4,
            1920,
            1080,
            30,
            logo="/tmp/logo.png",
        )

        filters = command[command.index("-filter_complex") + 1]
        self.assertIn("overlay=W-w-48:H-h-48:shortest=1[branded]", filters)

    def test_ffmpeg_command_freezes_once_then_resumes_the_source(self):
        command = ffmpeg_command(
            "/tmp/input.mp4",
            "/tmp/output.mp4",
            7.4,
            1920,
            1080,
            30,
            logo="/tmp/logo.png",
        )

        filters = command[command.index("-filter_complex") + 1]
        self.assertIn("split=3", filters)
        self.assertIn("trim=start=7.4:end=7.433333", filters)
        self.assertIn("concat=n=3:v=1:a=0", filters)
        self.assertIn("overlay=W-w-48:H-h-48:shortest=1", filters)
        self.assertNotIn("-t", command)

    def test_ffmpeg_caption_escapes_filtergraph_special_characters(self):
        command = ffmpeg_command(
            "/tmp/input.mp4",
            "/tmp/output.mp4",
            7.4,
            1920,
            1080,
            30,
            caption_text="Hold; freeze [now]: 100% \\done",
            caption_style="lower_third",
        )

        filters = command[command.index("-filter_complex") + 1]
        self.assertIn("expansion=none", filters)
        self.assertIn(r"Hold\; freeze \[now\]\\: 100% \\\\done", filters)

    def test_source_download_uses_a_browser_compatible_user_agent(self):
        self.assertEqual(download_request("https://example.test/video.mp4").get_header("User-agent"), "ulo-videos-render-worker/1.0")

    def test_fallback_caption_text_tolerates_empty_elements(self):
        self.assertIsNone(_caption_text_from_scene({"elements": []}))
        self.assertEqual(_caption_text_from_scene({"elements": [{"type": "character", "dialogue": {"text": "Hello"}}]}), "Hello")

    def test_update_job_detects_empty_patch_result(self):
        requests = []
        with patch.dict(os.environ, {"SUPABASE_URL": "https://supabase.example", "SUPABASE_SERVICE_ROLE_KEY": "service-role"}):
            with patch("ulo_videos.cloud_worker._json_request", lambda *args, **kwargs: requests.append((args, kwargs)) or []):
                with self.assertRaisesRegex(ValueError, "render job not found"):
                    _update_job("rj_missing", status="completed", progress=100)
        self.assertEqual(requests[0][1]["method"], "PATCH")

    def test_fallback_blob_upload_streams_mp4(self):
        def fake_urlopen(request, timeout):
            self.assertTrue(hasattr(request.data, "read"), "upload body must be a stream, not bytes")
            self.assertEqual(request.get_header("Content-length"), "7")
            self.assertEqual(request.data.read(), b"mp4data")
            return io.BytesIO(json.dumps({"url": "https://blob.example/render.mp4"}).encode())

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output.mp4"
            output.write_bytes(b"mp4data")
            with patch("ulo_videos.cloud_worker.urlopen", fake_urlopen):
                self.assertEqual(_put_blob("workspaces/w_1/renders/rj_123.mp4", output, "blob-token"), {"url": "https://blob.example/render.mp4"})

    def test_fallback_output_asset_upsert_is_idempotent(self):
        requests = []
        with patch.dict(os.environ, {"SUPABASE_URL": "https://supabase.example", "SUPABASE_SERVICE_ROLE_KEY": "service-role"}):
            with patch("ulo_videos.cloud_worker._json_request", lambda *args, **kwargs: requests.append((args, kwargs)) or [kwargs["payload"]]):
                asset_id = _create_output_asset({"id": "rj_123", "workspace_id": "w_1", "project_id": "p_1"}, "workspaces/w_1/renders/rj_123.mp4", "https://blob.example/render.mp4", 7)
        self.assertEqual(asset_id, "asset_rj_123")
        self.assertEqual(requests[0][0][0], "https://supabase.example/rest/v1/assets?on_conflict=id")
        self.assertEqual(requests[0][1]["method"], "POST")
        self.assertEqual(requests[0][1]["prefer"], "return=representation,resolution=merge-duplicates")


if __name__ == "__main__":
    unittest.main()
