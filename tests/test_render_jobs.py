import unittest

from ulo_videos.render_jobs import InvalidTransition, create_job, transition_job


class RenderJobTests(unittest.TestCase):
    def test_job_contains_an_immutable_snapshot_and_starts_queued(self):
        source = {"template": "x"}
        job = create_job("job-1", "workspace-1", "shot-1", source)
        source["template"] = "changed"
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["spec_snapshot"], {"template": "x"})

    def test_worker_states_progress_to_completed(self):
        job = create_job("job-1", "workspace-1", "shot-1", {})
        for status in ("preparing", "downloading_assets", "rendering", "uploading", "completed"):
            job = transition_job(job, status)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["progress"], 100)

    def test_completed_job_cannot_be_reopened(self):
        job = transition_job(create_job("job-1", "workspace-1", "shot-1", {}), "completed")
        with self.assertRaises(InvalidTransition):
            transition_job(job, "rendering")

