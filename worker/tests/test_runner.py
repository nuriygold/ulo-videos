import unittest

from worker.runner import build_worker_plan, execute_job


class WorkerPlanTests(unittest.TestCase):
    def _job(self):
        return {
            "id": "job-1",
            "spec_snapshot": {
                "version": 1,
                "source": {"video": "assets/source.mp4"},
                "trigger": {"type": "timestamp", "value": 7.4},
                "output": {"format": "mp4", "width": 1920, "height": 1080, "fps": 30},
                "elements": [],
                "captions": {"enabled": False, "style": "none"},
                "branding": {"logo": "assets/logo.svg"},
            },
        }

    def test_builds_a_real_mp4_pipeline_from_a_job_snapshot(self):
        plan = build_worker_plan(self._job(), "/tmp/job-1")
        self.assertEqual(plan["argv"][0], "ffmpeg")
        self.assertIn("trim=end=7.4", " ".join(plan["argv"]))
        self.assertTrue(plan["output"].endswith("/job-1/output.mp4"))

    def test_executes_job_and_updates_progress_and_output(self):
        updates = []
        uploaded = []

        def download(path, destination):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"input")

        def runner(argv, **kwargs):
            Path(argv[-1]).parent.mkdir(parents=True, exist_ok=True)
            Path(argv[-1]).write_bytes(b"mp4")
            return type("Result", (), {"returncode": 0, "stderr": ""})()

        from pathlib import Path
        result = execute_job(self._job(), "/tmp/job-1", download=download, upload=lambda path: uploaded.append(path), update=updates.append, runner=runner)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(uploaded[0].name, "output.mp4")
        self.assertEqual(updates[0], {"job_id": "job-1", "status": "preparing", "progress": 5})
        self.assertEqual(updates[-1]["status"], "completed")
