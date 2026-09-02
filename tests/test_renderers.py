import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from prompt_to_shot.renderers import (
    AssetPathError,
    CommandTimeoutError,
    MissingToolError,
    RendererError,
    Toolchain,
    prepare_output,
    plan_blender_render,
    plan_ffmpeg_render,
    resolve_relative_path,
    run_command,
)
from prompt_to_shot.templates import compile_scene


def scene_payload():
    return {
        "template": "interruption_spokescharacter_v1",
        "background_video": "assets/house_leak.mp4",
        "pause_at": 7.4,
        "character": {
            "asset": "assets/characters/lizard.blend",
            "position": "foreground_right",
            "entrance": "pop_in",
            "gesture": "shrug_and_point",
        },
        "dialogue": {
            "text": "Every landlord knows real estate isn't passive.",
            "voice": "local_voice_01",
            "lip_sync": "rhubarb",
        },
        "branding": {"logo": "assets/logo.svg", "caption_style": "lower_third"},
        "output": {"resolution": [1920, 1080]},
    }


class RenderersTestCase(unittest.TestCase):
    def setUp(self):
        # Resolve once so assertions match resolver output on symlinked temp dirs (macOS /var).
        root = Path(tempfile.mkdtemp(prefix="prompt-to-shot-renderers-")).resolve()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        self.root = root

    def touch(self, relative):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        return str(path)

    def ready_scene(self):
        self.touch("assets/house_leak.mp4")
        self.touch("assets/characters/lizard.blend")
        self.touch("assets/logo.svg")
        return compile_scene(scene_payload())

    def fake_toolchain(self, available=("ffmpeg", "blender"), filter_probe=None):
        paths = {name: f"/fake/bin/{name}" for name in available}
        return Toolchain(lookup=lambda name: paths.get(name), filter_probe=filter_probe)


class ResolveRelativePathTests(RenderersTestCase):
    def test_resolves_relative_paths_inside_project_root(self):
        resolved = resolve_relative_path(
            self.root, "assets/house_leak.mp4", "background_video"
        )

        self.assertEqual(resolved, str(self.root / "assets" / "house_leak.mp4"))

    def test_rejects_absolute_paths(self):
        for value in ("/etc/passwd", "C:\\media\\house_leak.mp4"):
            with self.subTest(value=value), self.assertRaises(AssetPathError):
                resolve_relative_path(self.root, value, "background_video")

    def test_rejects_paths_that_escape_project_root(self):
        for value in ("../outside.mp4", "assets/../../escape.mp4"):
            with self.subTest(value=value), self.assertRaises(AssetPathError):
                resolve_relative_path(self.root, value, "background_video")

    def test_rejects_symlinks_pointing_outside_project_root(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "secret.mp4"
            target.touch()
            (self.root / "assets").mkdir()
            os.symlink(target, self.root / "assets" / "leak.mp4")

            with self.assertRaises(AssetPathError):
                resolve_relative_path(self.root, "assets/leak.mp4", "background_video")

    def test_rejects_empty_or_non_string_paths(self):
        for value in ("", "   ", None, 7, True):
            with self.subTest(value=value), self.assertRaises(AssetPathError):
                resolve_relative_path(self.root, value, "background_video")

    def test_does_not_require_the_file_to_exist(self):
        resolved = resolve_relative_path(
            self.root, "assets/missing.mp4", "background_video"
        )

        self.assertTrue(resolved.startswith(str(self.root)))


class PlanFfmpegRenderTests(RenderersTestCase):
    def test_plans_deterministic_baseline_command(self):
        scene = self.ready_scene()
        toolchain = self.fake_toolchain(["ffmpeg"])

        first = plan_ffmpeg_render(scene, self.root, toolchain)
        second = plan_ffmpeg_render(scene, self.root, toolchain)

        self.assertEqual(first, second)
        self.assertEqual(first, json.loads(json.dumps(first)))
        argv = first["argv"]
        self.assertEqual(first["tool"], "ffmpeg")
        self.assertEqual(first["status"], "ready")
        self.assertEqual(first["missing_assets"], [])
        self.assertEqual(argv[0], "/fake/bin/ffmpeg")
        self.assertTrue(all(isinstance(arg, str) for arg in argv))
        self.assertEqual(
            first["assets"]["background_video"],
            str(self.root / "assets" / "house_leak.mp4"),
        )
        self.assertEqual(argv[argv.index("-i") + 1], first["assets"]["background_video"])
        filters = argv[argv.index("-vf") + 1]
        self.assertIn("trim=end=7.4", filters)
        self.assertIn("tpad=stop_mode=clone", filters)
        self.assertIn("scale=1920:1080", filters)
        self.assertIn("fps=30", filters)
        self.assertEqual(first["output"]["path"], str(self.root / "build" / "preview.mp4"))
        self.assertEqual(argv[-1], first["output"]["path"])
        self.assertEqual(first["output"]["format"], "mp4")
        self.assertEqual(first["output"]["resolution"], [1920, 1080])
        self.assertEqual(first["output"]["fps"], 30)
        self.assertIn("-an", argv)
        self.assertEqual(first["captions"]["style"], "lower_third")
        self.assertEqual(first["captions"]["text"], scene["dialogue"]["text"])
        self.assertFalse(first["captions"]["applied"])
        self.assertTrue(first["captions"]["reason"])

    def test_reports_missing_asset_files_as_named_status(self):
        scene = compile_scene(scene_payload())

        plan = plan_ffmpeg_render(scene, self.root, self.fake_toolchain(["ffmpeg"]))

        self.assertEqual(plan["status"], "missing_assets")
        missing = {entry["field"]: entry["path"] for entry in plan["missing_assets"]}
        self.assertEqual(
            set(missing), {"background_video", "character.asset", "branding.logo"}
        )
        self.assertIn("-i", plan["argv"])
        self.assertTrue(plan["argv"][0].endswith("ffmpeg"))

    def test_requires_ffmpeg_and_names_missing_tool(self):
        scene = self.ready_scene()

        with self.assertRaises(MissingToolError) as ctx:
            plan_ffmpeg_render(scene, self.root, self.fake_toolchain([]))

        self.assertIn("ffmpeg", str(ctx.exception))

    def test_rejects_output_paths_that_escape_project_root(self):
        scene = self.ready_scene()

        with self.assertRaises(AssetPathError):
            plan_ffmpeg_render(
                scene, self.root, self.fake_toolchain(["ffmpeg"]), output_name="../evil.mp4"
            )

    def test_rejects_unsafe_scene_asset_paths(self):
        scene = compile_scene(scene_payload())
        scene["background_video"] = "/etc/house_leak.mp4"

        with self.assertRaises(AssetPathError) as ctx:
            plan_ffmpeg_render(scene, self.root, self.fake_toolchain(["ffmpeg"]))

        self.assertIn("background_video", str(ctx.exception))

    def test_plans_burned_in_caption_when_drawtext_is_supported(self):
        scene = self.ready_scene()
        chain = self.fake_toolchain(["ffmpeg"], filter_probe=lambda tool, name: True)

        plan = plan_ffmpeg_render(scene, self.root, chain)

        self.assertTrue(plan["captions"]["applied"])
        self.assertIsNone(plan["captions"]["reason"])
        filters = plan["argv"][plan["argv"].index("-vf") + 1]
        self.assertIn(
            r"drawtext=text=Every landlord knows real estate isn\\\'t passive."
            r":expansion=none:x=(w-text_w)/2:y=h-th-60",
            filters,
        )

    def test_caption_text_escapes_drawtext_special_characters(self):
        scene = self.ready_scene()
        scene["dialogue"]["text"] = "Isn't it: 100% \\done"
        chain = self.fake_toolchain(["ffmpeg"], filter_probe=lambda tool, name: True)

        plan = plan_ffmpeg_render(scene, self.root, chain)

        filters = plan["argv"][plan["argv"].index("-vf") + 1]
        self.assertIn(r"drawtext=text=Isn\\\'t it\\: 100% \\\\done:expansion=none", filters)

    def test_keeps_metadata_only_caption_when_drawtext_is_unavailable(self):
        scene = self.ready_scene()
        chain = self.fake_toolchain(["ffmpeg"], filter_probe=lambda tool, name: False)

        plan = plan_ffmpeg_render(scene, self.root, chain)

        self.assertFalse(plan["captions"]["applied"])
        self.assertIn("drawtext", plan["captions"]["reason"])
        self.assertNotIn("drawtext", plan["argv"][plan["argv"].index("-vf") + 1])

    def test_caption_style_none_omits_burn_in_even_when_drawtext_is_supported(self):
        scene = self.ready_scene()
        scene["branding"]["caption_style"] = "none"
        chain = self.fake_toolchain(["ffmpeg"], filter_probe=lambda tool, name: True)

        plan = plan_ffmpeg_render(scene, self.root, chain)

        self.assertFalse(plan["captions"]["applied"])
        self.assertIn("none", plan["captions"]["reason"])
        self.assertNotIn("drawtext", plan["argv"][plan["argv"].index("-vf") + 1])


class PlanBlenderRenderTests(RenderersTestCase):
    def test_plans_headless_render_command(self):
        scene = self.ready_scene()

        plan = plan_blender_render(scene, self.root, self.fake_toolchain(["blender"]))

        argv = plan["argv"]
        self.assertEqual(plan["tool"], "blender")
        self.assertEqual(plan["status"], "ready")
        self.assertEqual(argv[0], "/fake/bin/blender")
        self.assertEqual(argv[argv.index("-b") + 1], plan["assets"]["character.asset"])
        self.assertEqual(
            plan["assets"]["character.asset"],
            str(self.root / "assets" / "characters" / "lizard.blend"),
        )
        self.assertIn("--factory-startup", argv)
        self.assertEqual(
            plan["output"]["path"], str(self.root / "build" / "blender-frame0001.png")
        )
        self.assertEqual(argv[argv.index("-o") + 1] + "0001.png", plan["output"]["path"])
        self.assertEqual(plan, json.loads(json.dumps(plan)))

    def test_requires_blender_and_names_missing_tool(self):
        scene = self.ready_scene()

        with self.assertRaises(MissingToolError) as ctx:
            plan_blender_render(scene, self.root, self.fake_toolchain(["ffmpeg"]))

        self.assertIn("blender", str(ctx.exception))

    def test_reports_missing_character_asset(self):
        scene = compile_scene(scene_payload())

        plan = plan_blender_render(scene, self.root, self.fake_toolchain(["blender"]))

        self.assertEqual(plan["status"], "missing_assets")
        self.assertEqual(
            [entry["field"] for entry in plan["missing_assets"]], ["character.asset"]
        )


class PrepareOutputTests(RenderersTestCase):
    def test_creates_the_output_directory_for_a_plan(self):
        scene = self.ready_scene()
        plan = plan_ffmpeg_render(scene, self.root, self.fake_toolchain(["ffmpeg"]))
        self.assertFalse((self.root / "build").exists())

        path = prepare_output(plan)

        self.assertEqual(path, plan["output"]["path"])
        self.assertTrue((self.root / "build").is_dir())

    def test_is_a_no_op_without_an_output_path(self):
        self.assertIsNone(prepare_output({"status": "ready", "argv": []}))


class ToolchainTests(RenderersTestCase):
    def test_status_reports_missing_tools_without_raising(self):
        chain = Toolchain(
            lookup=lambda name: "/opt/homebrew/bin/ffmpeg" if name == "ffmpeg" else None
        )

        status = chain.status()

        self.assertTrue(status["ffmpeg"]["available"])
        self.assertEqual(status["ffmpeg"]["path"], "/opt/homebrew/bin/ffmpeg")
        self.assertFalse(status["blender"]["available"])
        self.assertIsNone(status["blender"]["path"])

    def test_require_raises_named_error_for_missing_tool(self):
        chain = Toolchain(lookup=lambda name: None)

        with self.assertRaises(MissingToolError) as ctx:
            chain.require("blender")

        self.assertIn("blender", str(ctx.exception))

    def test_default_lookup_uses_path(self):
        chain = Toolchain()

        self.assertEqual(chain.resolve("ffmpeg"), shutil.which("ffmpeg"))

    def test_filter_probe_is_injectable_and_cached(self):
        calls = []

        def probe(tool, name):
            calls.append((tool, name))
            return True

        chain = Toolchain(lookup=lambda name: "/fake/bin/ffmpeg", filter_probe=probe)

        self.assertTrue(chain.supports_filter("ffmpeg", "drawtext"))
        self.assertTrue(chain.supports_filter("ffmpeg", "drawtext"))
        self.assertEqual(calls, [("ffmpeg", "drawtext")])

    def test_supports_filter_returns_false_without_an_executable(self):
        chain = Toolchain(lookup=lambda name: None)

        self.assertFalse(chain.supports_filter("ffmpeg", "drawtext"))


class RunCommandTests(RenderersTestCase):
    def test_captures_stdout_stderr_and_returncode(self):
        argv = [sys.executable, "-c", "print('planned output')"]

        result = run_command(argv)

        self.assertEqual(result["argv"], argv)
        self.assertEqual(result["returncode"], 0)
        self.assertIn("planned output", result["stdout"])

    def test_reports_nonzero_exit_without_raising(self):
        result = run_command([sys.executable, "-c", "import sys; sys.exit(3)"])

        self.assertEqual(result["returncode"], 3)

    def test_passes_arguments_verbatim_without_shell_interpolation(self):
        payload = "hello; echo pwned | cat && echo pwned-again"

        result = run_command([sys.executable, "-c", "import sys; print(sys.argv[1])", payload])

        self.assertEqual(result["stdout"].strip(), payload)

    def test_raises_named_error_when_executable_missing(self):
        with self.assertRaises(MissingToolError) as ctx:
            run_command(["definitely-not-a-real-tool-42"])

        self.assertIn("definitely-not-a-real-tool-42", str(ctx.exception))

    def test_times_out_and_names_the_executable(self):
        with self.assertRaises(CommandTimeoutError) as ctx:
            run_command([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.2)

        self.assertIn("python", str(ctx.exception))
        self.assertIn("0.2", str(ctx.exception))

    def test_rejects_shell_strings_and_non_string_arguments(self):
        for argv in ("ffmpeg -y -i clip.mp4", [], [sys.executable, 7]):
            with self.subTest(argv=argv), self.assertRaises(RendererError):
                run_command(argv)


if __name__ == "__main__":
    unittest.main()