import json
import unittest

from ulo_videos.cloud_worker import download_request, queue_message, ffmpeg_command


class CloudWorkerContractTests(unittest.TestCase):
    def test_queue_message_requires_bearer_secret_and_job_id(self):
        self.assertEqual(queue_message(b'{"renderJobId":"rj_123"}', "Bearer secret", "secret"), {"renderJobId": "rj_123"})
        with self.assertRaises(ValueError):
            queue_message(b"{}", "Bearer secret", "secret")
        with self.assertRaises(PermissionError):
            queue_message(b'{"renderJobId":"rj_123"}', "Bearer wrong", "secret")

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


if __name__ == "__main__":
    unittest.main()
