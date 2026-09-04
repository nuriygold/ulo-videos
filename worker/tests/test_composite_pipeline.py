import base64
import shutil
import subprocess
import tempfile
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
                    "dialogue": {"text": "A clearer way.", "voice": "", "lip_sync": ""},
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
        self.assertIn("[freeze_source]trim=end=7.4,reverse,trim=end=", filters)
        self.assertNotIn("[before]tpad", filters)
        self.assertIn("[before][hold][after]concat=n=3:v=1:a=0[assembled]", filters)
        self.assertIn("[assembled]scale=1920:1080,fps=30[scene]", filters)
        self.assertIn("overlay=x=0:y=0", filters)
        self.assertIn("eof_action=pass", filters)
        self.assertIn("drawtext=text='A clearer way.'", filters)
        self.assertIn("enable='between(t,7.4,9.4)'", filters)
        self.assertIn("shortest=1", filters)
        self.assertIn("-shortest", plan.ffmpeg_argv)
        self.assertTrue(plan.output.endswith("/tmp/render-job/output.mp4"))

    def test_execution_reports_blender_then_encoding_before_upload(self):
        from worker.service import execute_render_job

        job = {
            "id": "rj_123", "workspace_id": "w_123", "project_id": "p_123",
            "spec_snapshot": {
                "source": {"video": "https://storage.example/source.mp4"},
                "trigger": {"type": "timestamp", "value": 7.4},
                "elements": [{"type": "character", "asset": "https://storage.example/lizard.blend", "position": "foreground_right", "entrance": {"type": "pop_in"}, "performance": {"gesture": "shrug_and_point"}, "dialogue": {"text": "Caption", "voice": "", "lip_sync": ""}}],
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

    def test_requested_voice_or_lip_sync_fails_before_assets_are_downloaded(self):
        from worker.service import execute_render_job

        job = {
            "id": "rj_voice", "workspace_id": "w_123", "project_id": "p_123",
            "spec_snapshot": {
                "source": {"video": "https://storage.example/source.mp4"},
                "trigger": {"type": "timestamp", "value": 1},
                "elements": [{"type": "character", "asset": "https://storage.example/lizard.blend", "position": "foreground_right", "entrance": {"type": "pop_in"}, "performance": {"gesture": "wave"}, "dialogue": {"text": "Speak", "voice": "alloy", "lip_sync": "rhubarb"}}],
                "captions": {"enabled": True, "style": "lower_third"},
                "branding": {"logo": "https://storage.example/logo.svg"},
                "output": {"width": 1920, "height": 1080, "fps": 30},
            },
        }
        updates = []
        case = self

        class ControlPlane:
            def get_job(self, job_id): return job
            def update_job(self, job_id, **fields): updates.append(fields)
            def download(self, url, destination): case.fail("unsupported performance must fail before download")

        with self.assertRaisesRegex(Exception, "unsupported_performance"):
            execute_render_job("rj_voice", ControlPlane(), run_command=lambda argv: self.fail("unsupported performance must not run commands"))
        self.assertEqual(updates[-1]["error_code"], "unsupported_performance")

    def test_raster_logo_is_used_directly_without_svg_conversion(self):
        from worker.pipeline import build_composite_plan

        scene = {
            "source": {"video": "https://storage.example/source.mp4"}, "trigger": {"type": "timestamp", "value": 1},
            "elements": [{"type": "character", "asset": "https://storage.example/lizard.blend", "position": "foreground_center", "entrance": {"type": "pop_in"}, "performance": {"gesture": "wave"}, "dialogue": {"text": "Hi", "voice": "", "lip_sync": ""}}],
            "captions": {"enabled": False, "style": "none"}, "branding": {"logo": "https://storage.example/logo.png"},
            "output": {"width": 1920, "height": 1080, "fps": 30},
        }
        plan = build_composite_plan(scene, "/tmp/raster-logo")
        self.assertFalse(plan.rasterize_logo)
        self.assertEqual(plan.logo_image, plan.logo_source)

    def test_blender_script_applies_position_and_fades_material_alpha(self):
        script = (Path(__file__).parents[1] / "blender_character.py").read_text()
        self.assertIn("def character_position_offset", script)
        self.assertIn("foreground_left", script)
        self.assertIn("foreground_center", script)
        self.assertIn("foreground_right", script)
        self.assertIn("def fade_materials", script)
        self.assertIn("keyframe_insert(data_path=\"default_value\"", script)

    @unittest.skipUnless(shutil.which("ffmpeg"), "requires FFmpeg")
    def test_actual_ffmpeg_assembly_adds_only_the_two_second_freeze(self):
        from worker.pipeline import build_composite_plan

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_dir = root / "input"
            character_dir = root / "character"
            input_dir.mkdir()
            character_dir.mkdir()
            source = input_dir / "source.mp4"
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=10", "-t", "3",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
            ], check=True, capture_output=True)
            transparent_png = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADElEQVR42mNk+M/wHwAF/gL+24dD2QAAAABJRU5ErkJggg=="
            )
            (input_dir / "logo.png").write_bytes(transparent_png)
            (character_dir / "character_00001.png").write_bytes(transparent_png)
            scene = {
                "source": {"video": "https://storage.example/source.mp4"}, "trigger": {"type": "timestamp", "value": 1},
                "elements": [{"type": "character", "asset": "https://storage.example/lizard.blend", "position": "foreground_center", "entrance": {"type": "pop_in"}, "performance": {"gesture": "wave"}, "dialogue": {"text": "caption", "voice": "", "lip_sync": ""}}],
                "captions": {"enabled": False, "style": "none"}, "branding": {"logo": "https://storage.example/logo.png"},
                "output": {"width": 64, "height": 64, "fps": 10},
            }
            plan = build_composite_plan(scene, root)
            subprocess.run(plan.ffmpeg_argv, check=True, capture_output=True)
            duration = float(subprocess.check_output([
                "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", plan.output,
            ], text=True))
            self.assertGreater(duration, 4.8)
            self.assertLess(duration, 5.3)


if __name__ == "__main__":
    unittest.main()
