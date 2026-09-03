import json
import unittest

from ulo_videos.cloud_worker import queue_message, ffmpeg_command


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


if __name__ == "__main__":
    unittest.main()
