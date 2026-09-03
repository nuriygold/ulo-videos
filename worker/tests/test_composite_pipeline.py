import unittest
from pathlib import Path


class CompositePipelineTests(unittest.TestCase):
    def test_character_scene_builds_blender_plate_and_ffmpeg_composite(self):
        from worker.pipeline import build_composite_plan

        plan = build_composite_plan(
            scene={
                "source": {"video": "https://storage.example/source.mp4"},
                "trigger": {"type": "timestamp", "value": 7.4},
                "elements": [{
                    "id": "spokesperson",
                    "type": "character",
                    "asset": "https://storage.example/lizard.blend",
                    "position": "foreground_right",
                    "entrance": {"type": "pop_in", "duration": 0.35},
                    "performance": {"gesture": "shrug_and_point"},
                    "dialogue": {"text": "A clearer way.", "voice": "alloy", "lip_sync": "rhubarb"},
                }],
                "captions": {"enabled": True, "style": "lower_third"},
                "branding": {"logo": "https://storage.example/logo.svg"},
                "continuation": {"action": "resume"},
                "output": {"format": "mp4", "width": 1920, "height": 1080, "fps": 30},
            },
            workdir="/tmp/render-job",
        )

        self.assertEqual(plan.blender_argv[0], "blender")
        self.assertIn("lizard.blend", " ".join(plan.blender_argv))
        self.assertIn("--gesture", plan.blender_argv)
        self.assertIn("shrug_and_point", plan.blender_argv)
        self.assertEqual(plan.ffmpeg_argv.count("-i"), 3)
        filters = plan.ffmpeg_argv[plan.ffmpeg_argv.index("-filter_complex") + 1]
        self.assertIn("overlay=W-w-48:H-h-48", filters)
        self.assertIn("overlay=x=", filters)
        self.assertIn("eof_action=pass", filters)
        self.assertIn("drawtext=text='A clearer way.'", filters)
        self.assertNotIn("-shortest", plan.ffmpeg_argv)
        self.assertTrue(plan.output.endswith("/tmp/render-job/output.mp4"))

    def test_execution_reports_blender_then_encoding_before_upload(self):
        from worker.service import execute_render_job

        job = {
            "id": "rj_123", "workspace_id": "w_123", "project_id": "p_123",
            "spec_snapshot": {
                "source": {"video": "https://storage.example/source.mp4"},
                "trigger": {"type": "timestamp", "value": 7.4},
                "elements": [{"type": "character", "asset": "https://storage.example/lizard.blend", "position": "foreground_right", "entrance": {"type": "pop_in"}, "performance": {"gesture": "shrug_and_point"}, "dialogue": {"text": "Caption", "voice": "alloy", "lip_sync": "rhubarb"}}],
                "captions": {"enabled": True, "style": "lower_third"},
                "branding": {"logo": "https://storage.example/logo.svg"},
                "output": {"width": 1920, "height": 1080, "fps": 30},
            },
        }
        updates = []

        class ControlPlane:
            def get_job(self, job_id): return job
            def update_job(self, job_id, **fields): updates.append(fields)
            def download(self, url, destination):
                Path(destination).parent.mkdir(parents=True, exist_ok=True)
                Path(destination).write_bytes(b"asset")
            def upload_output(self, job_arg, output): return "asset_rj_123"

        def run_command(argv):
            if argv[0] == "ffmpeg":
                Path(argv[-1]).parent.mkdir(parents=True, exist_ok=True)
                Path(argv[-1]).write_bytes(b"mp4")

        result = execute_render_job("rj_123", ControlPlane(), run_command=run_command)
        self.assertEqual(result["status"], "completed")
        self.assertEqual([update["status"] for update in updates], ["preparing", "downloading_assets", "building_scene", "rendering", "encoding", "uploading", "completed"])

    def test_completed_job_is_not_rendered_again_when_the_queue_retries(self):
        from worker.service import execute_render_job
        case = self

        class ControlPlane:
            def get_job(self, job_id): return {"id": job_id, "status": "completed", "output_asset_id": "asset_rj_123"}
            def update_job(self, job_id, **fields): case.fail("completed job must not be updated")

        result = execute_render_job("rj_123", ControlPlane(), run_command=lambda argv: self.fail("completed job must not run"))
        self.assertEqual(result, {"jobId": "rj_123", "status": "completed", "progress": 100, "outputAssetId": "asset_rj_123"})

    def test_raster_logo_is_used_directly_without_svg_conversion(self):
        from worker.pipeline import build_composite_plan

        scene = {
            "source": {"video": "https://storage.example/source.mp4"}, "trigger": {"type": "timestamp", "value": 1},
            "elements": [{"type": "character", "asset": "https://storage.example/lizard.blend", "position": "foreground_center", "entrance": {"type": "pop_in"}, "performance": {"gesture": "wave"}, "dialogue": {"text": "Hi", "voice": "alloy", "lip_sync": "rhubarb"}}],
            "captions": {"enabled": False, "style": "none"}, "branding": {"logo": "https://storage.example/logo.png"},
            "output": {"width": 1920, "height": 1080, "fps": 30},
        }
        plan = build_composite_plan(scene, "/tmp/raster-logo")
        self.assertFalse(plan.rasterize_logo)
        self.assertEqual(plan.logo_image, plan.logo_source)


if __name__ == "__main__":
    unittest.main()
