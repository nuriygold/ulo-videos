import base64
import os
import shutil
import subprocess
import tempfile
import unittest
import subprocess as subprocess_module
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
        self.assertIn("[freeze_source]trim=start=7.4:end=7.433333", filters)
        self.assertNotIn("[before]tpad", filters)
        self.assertIn("[before][hold][after]concat=n=3:v=1:a=0[assembled]", filters)
        self.assertIn("[assembled]scale=1920:1080,fps=30[scene]", filters)
        self.assertIn("overlay=x=0:y=0", filters)
        self.assertIn("eof_action=pass", filters)
        self.assertIn("drawtext=text='A clearer way.'", filters)
        self.assertIn("enable='between(t,7.4,9.4)'", filters)
        self.assertIn("overlay=W-w-48:H-h-48:eof_action=pass", filters)
        self.assertNotIn("shortest=1", filters)
        self.assertNotIn("-shortest", plan.ffmpeg_argv)
        self.assertTrue(plan.output.endswith("/tmp/render-job/output.mp4"))

    def test_gltf_character_uses_the_blender_import_path_and_keeps_the_uploaded_filename(self):
        from worker.pipeline import build_composite_plan

        scene = {
            "source": {"video": "https://storage.example/source.mp4"}, "trigger": {"type": "timestamp", "value": 1},
            "elements": [{"type": "character", "asset": "https://storage.example/Character%20Wave.gltf", "position": "foreground_center", "entrance": {"type": "pop_in"}, "performance": {"gesture": "wave"}, "dialogue": {"text": "Hi", "voice": "", "lip_sync": ""}}],
            "captions": {"enabled": False, "style": "none"}, "branding": {"logo": "https://storage.example/logo.png"},
            "output": {"width": 1920, "height": 1080, "fps": 30},
        }

        plan = build_composite_plan(scene, "/tmp/import-character")

        self.assertTrue(str(plan.character).endswith("Character%20Wave.gltf"))
        self.assertIn("--character-format", plan.blender_argv)
        self.assertIn(".gltf", plan.blender_argv)
        self.assertIn("--imported-blend", plan.blender_argv)
        self.assertNotIn(str(plan.character), plan.blender_argv[:3])

    def test_blender_gesture_normalization_keeps_unicode_word_boundaries(self):
        import importlib.util
        import sys
        import types

        fake_bpy = types.ModuleType("bpy")
        previous_bpy = sys.modules.get("bpy")
        sys.modules["bpy"] = fake_bpy
        try:
            path = Path(__file__).parents[1] / "blender_character.py"
            spec = importlib.util.spec_from_file_location("blender_character_test", path)
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
            self.assertEqual(module.normalized("  WＡVE---Idle  "), "wave_idle")
        finally:
            if previous_bpy is None:
                del sys.modules["bpy"]
            else:
                sys.modules["bpy"] = previous_bpy

    def test_blender_rejects_ambiguous_gesture_actions(self):
        import importlib.util
        import sys
        import types

        fake_bpy = types.ModuleType("bpy")
        previous_bpy = sys.modules.get("bpy")
        sys.modules["bpy"] = fake_bpy
        try:
            path = Path(__file__).parents[1] / "blender_character.py"
            spec = importlib.util.spec_from_file_location("blender_character_test", path)
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
            fake_bpy.context = types.SimpleNamespace(scene=types.SimpleNamespace(
                objects=[types.SimpleNamespace(type="ARMATURE")], camera=object(),
            ))
            fake_bpy.data = types.SimpleNamespace(actions=[
                types.SimpleNamespace(name="Wave Action"), types.SimpleNamespace(name="wave_action"),
            ])
            module.arguments = lambda: types.SimpleNamespace(gesture="wave action", character=None)
            with self.assertRaisesRegex(Exception, "matches multiple actions"):
                module.main()
        finally:
            if previous_bpy is None:
                del sys.modules["bpy"]
            else:
                sys.modules["bpy"] = previous_bpy

    def test_blender_rejects_gltf_external_resources(self):
        import importlib.util
        import json
        import sys
        import types

        fake_bpy = types.ModuleType("bpy")
        previous_bpy = sys.modules.get("bpy")
        sys.modules["bpy"] = fake_bpy
        try:
            path = Path(__file__).parents[1] / "blender_character.py"
            spec = importlib.util.spec_from_file_location("blender_character_test", path)
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
            with tempfile.TemporaryDirectory() as temporary:
                character = Path(temporary) / "character.gltf"
                character.write_text(json.dumps({"buffers": [{"uri": "mesh.bin"}]}))
                with self.assertRaisesRegex(RuntimeError, "external resources"):
                    module.reject_external_gltf_resources(character, ".gltf")
        finally:
            if previous_bpy is None:
                del sys.modules["bpy"]
            else:
                sys.modules["bpy"] = previous_bpy

    def test_imported_character_selects_single_camera(self):
        import importlib.util
        import sys
        import types

        fake_bpy = types.ModuleType("bpy")
        previous_bpy = sys.modules.get("bpy")
        sys.modules["bpy"] = fake_bpy
        try:
            path = Path(__file__).parents[1] / "blender_character.py"
            spec = importlib.util.spec_from_file_location("blender_character_test", path)
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
            camera = types.SimpleNamespace(type="CAMERA")
            fake_bpy.context = types.SimpleNamespace(scene=types.SimpleNamespace(camera=None, objects=[camera]))
            module.select_imported_camera()
            self.assertIs(fake_bpy.context.scene.camera, camera)
        finally:
            if previous_bpy is None:
                del sys.modules["bpy"]
            else:
                sys.modules["bpy"] = previous_bpy

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
            if argv[0] == "blender":
                character_dir = Path(argv[argv.index("--output-dir") + 1])
                character_dir.mkdir(parents=True, exist_ok=True)
                for frame in range(1, 61):
                    (character_dir / f"character_{frame:05d}.png").write_bytes(b"png")
            if argv[0] == "ffmpeg":
                Path(argv[-1]).parent.mkdir(parents=True, exist_ok=True)
                Path(argv[-1]).write_bytes(b"mp4")

        result = execute_render_job("rj_123", ControlPlane(), run_command=run_command)
        self.assertEqual(result["status"], "completed")
        self.assertEqual([update["status"] for update in updates], ["preparing", "downloading_assets", "building_scene", "rendering", "encoding", "uploading", "completed"])

    def test_stale_character_frames_are_removed_and_incomplete_blender_output_fails_before_ffmpeg(self):
        from worker.service import execute_render_job

        job = {
            "id": "rj_123", "spec_snapshot": {
                "source": {"video": "https://storage.example/source.mp4"}, "trigger": {"type": "timestamp", "value": 1},
                "elements": [{"type": "character", "asset": "https://storage.example/character.glb", "position": "foreground_center", "entrance": {"type": "pop_in"}, "performance": {"gesture": "wave"}, "dialogue": {"text": "Hi", "voice": "", "lip_sync": ""}}],
                "captions": {"enabled": False, "style": "none"}, "branding": {"logo": "https://storage.example/logo.png"},
                "output": {"width": 1920, "height": 1080, "fps": 30},
            },
        }
        updates = []
        ffmpeg_ran = False

        class ControlPlane:
            def get_job(self, job_id): return job
            def update_job(self, job_id, **fields): updates.append(fields)
            def download(self, url, destination):
                Path(destination).parent.mkdir(parents=True, exist_ok=True)
                Path(destination).write_bytes(b"asset")

        def run_command(argv):
            nonlocal ffmpeg_ran
            if argv[0] == "blender":
                character_dir = Path(argv[argv.index("--output-dir") + 1])
                self.assertFalse((character_dir / "character_00001.png").exists())
                (character_dir / "character_00001.png").write_bytes(b"new")
            if argv[0] == "ffmpeg":
                ffmpeg_ran = True

        with self.assertRaisesRegex(RuntimeError, "fresh complete character frame sequence"):
            execute_render_job("rj_123", ControlPlane(), run_command=run_command)
        self.assertFalse(ffmpeg_ran)
        self.assertEqual(updates[-1]["error_code"], "render_failed")
        self.assertIn("fresh complete character frame sequence", updates[-1]["error_message"])

    def test_import_validation_failure_is_reported_as_render_failed(self):
        from worker.service import execute_render_job

        job = {
            "id": "rj_123", "spec_snapshot": {
                "source": {"video": "https://storage.example/source.mp4"}, "trigger": {"type": "timestamp", "value": 1},
                "elements": [{"type": "character", "asset": "https://storage.example/character.gltf", "position": "foreground_center", "entrance": {"type": "pop_in"}, "performance": {"gesture": "wave"}, "dialogue": {"text": "Hi", "voice": "", "lip_sync": ""}}],
                "captions": {"enabled": False, "style": "none"}, "branding": {"logo": "https://storage.example/logo.png"},
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

        def run_command(argv):
            if argv[0] == "blender":
                raise RuntimeError(".gltf character references external resources (mesh.bin)")

        with self.assertRaisesRegex(RuntimeError, "external resources"):
            execute_render_job("rj_123", ControlPlane(), run_command=run_command)
        self.assertEqual(updates[-1], {
            "status": "failed", "progress": 100, "error_code": "render_failed",
            "error_message": ".gltf character references external resources (mesh.bin)",
        })

    def test_completed_job_is_not_rendered_again_when_the_queue_retries(self):
        from worker.service import execute_render_job
        case = self

        class ControlPlane:
            def get_job(self, job_id): return {"id": job_id, "status": "completed", "output_asset_id": "asset_rj_123"}
            def update_job(self, job_id, **fields): case.fail("completed job must not be updated")

        result = execute_render_job("rj_123", ControlPlane(), run_command=lambda argv: self.fail("completed job must not run"))
        self.assertEqual(result, {"jobId": "rj_123", "status": "completed", "progress": 100, "outputAssetId": "asset_rj_123"})

    def test_trigger_at_zero_uses_first_frame_for_freeze_instead_of_empty_trim(self):
        from worker.pipeline import build_composite_plan

        scene = {
            "source": {"video": "https://storage.example/source.mp4"}, "trigger": {"type": "timestamp", "value": 0},
            "elements": [{"type": "character", "asset": "https://storage.example/lizard.blend", "position": "foreground_right", "entrance": {"type": "pop_in"}, "performance": {"gesture": "wave"}, "dialogue": {"text": "Speak", "voice": "", "lip_sync": ""}}],
            "captions": {"enabled": False, "style": "none"}, "branding": {"logo": "https://storage.example/logo.svg"},
            "output": {"width": 1920, "height": 1080, "fps": 30},
        }

        plan = build_composite_plan(scene, "/tmp/zero-trigger")
        filters = plan.ffmpeg_argv[plan.ffmpeg_argv.index("-filter_complex") + 1]
        self.assertIn("[freeze_source]trim=start=0:end=0.033333", filters)
        self.assertNotIn("[freeze_source]trim=end=0,reverse", filters)

    def test_legacy_voice_and_lip_sync_values_still_plan_a_silent_captioned_render(self):
        from worker.pipeline import build_composite_plan

        scene = {
            "source": {"video": "https://storage.example/source.mp4"}, "trigger": {"type": "timestamp", "value": 1},
            "elements": [{"type": "character", "asset": "https://storage.example/lizard.blend", "position": "foreground_right", "entrance": {"type": "pop_in"}, "performance": {"gesture": "wave"}, "dialogue": {"text": "Speak", "voice": "alloy", "lip_sync": "rhubarb"}}],
            "captions": {"enabled": True, "style": "lower_third"}, "branding": {"logo": "https://storage.example/logo.svg"},
            "output": {"width": 1920, "height": 1080, "fps": 30},
        }

        plan = build_composite_plan(scene, "/tmp/legacy-voice")
        filters = plan.ffmpeg_argv[plan.ffmpeg_argv.index("-filter_complex") + 1]
        self.assertIn("drawtext=text='Speak'", filters)
        self.assertIn("-an", plan.ffmpeg_argv)

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

    def test_blender_render_engine_prefers_available_eevee_variants(self):
        import importlib.util
        import sys
        import types

        fake_bpy = types.ModuleType("bpy")
        previous_bpy = sys.modules.get("bpy")
        sys.modules["bpy"] = fake_bpy
        try:
            path = Path(__file__).parents[1] / "blender_character.py"
            spec = importlib.util.spec_from_file_location("blender_character_test", path)
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
            scene = types.SimpleNamespace(render=types.SimpleNamespace(
                engine=None,
                bl_rna=types.SimpleNamespace(properties={
                    "engine": types.SimpleNamespace(enum_items=[types.SimpleNamespace(identifier="BLENDER_EEVEE")]),
                }),
            ))
            self.assertEqual(module.set_render_engine(scene), "BLENDER_EEVEE")
            self.assertEqual(scene.render.engine, "BLENDER_EEVEE")
        finally:
            if previous_bpy is None:
                del sys.modules["bpy"]
            else:
                sys.modules["bpy"] = previous_bpy

    def test_integration_fixture_rejects_non_blender_50_demo_asset(self):
        import importlib.util

        path = Path(__file__).parents[1] / "integration_fixtures.py"
        spec = importlib.util.spec_from_file_location("integration_fixtures_test", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            asset = Path(temporary) / "demo-character.blend"
            asset.write_bytes(b"BLENDER17-01v0520REND")
            with self.assertRaisesRegex(SystemExit, "Blender 5.0"):
                module.require_blender_50_asset(asset)

    def test_integration_fixture_run_prints_failing_command_output(self):
        import importlib.util
        from unittest.mock import patch

        path = Path(__file__).parents[1] / "integration_fixtures.py"
        spec = importlib.util.spec_from_file_location("integration_fixtures_test", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        result = subprocess_module.CompletedProcess(["tool"], 1, "out", "err")
        with patch("subprocess.run", return_value=result):
            with self.assertRaises(subprocess_module.CalledProcessError):
                module.run(["tool"])

    def test_integration_fixture_embeds_gltf_sidecars(self):
        import importlib.util
        import json

        path = Path(__file__).parents[1] / "integration_fixtures.py"
        spec = importlib.util.spec_from_file_location("integration_fixtures_test", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            gltf = root / "valid.gltf"
            sidecar = root / "valid.bin"
            sidecar.write_bytes(b"mesh")
            gltf.write_text(json.dumps({"buffers": [{"uri": "valid.bin", "byteLength": 4}]}), encoding="utf-8")
            module.embed_gltf_resources(gltf)
            self.assertFalse(sidecar.exists())
            self.assertIn("data:application/octet-stream;base64,", gltf.read_text(encoding="utf-8"))

    @unittest.skipUnless(os.environ.get("ULO_RUN_FFMPEG_INTEGRATION") == "1" and shutil.which("ffmpeg"), "requires ULO_RUN_FFMPEG_INTEGRATION=1 and FFmpeg")
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
