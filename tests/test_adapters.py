import json
import shutil
import tempfile
import unittest
from pathlib import Path

from prompt_to_shot.adapters import (
    ADAPTER_TOOLS,
    PIPER_OUTPUT_NAME,
    RHUBARB_OUTPUT_NAME,
    adapter_status,
    plan_blender_render,
    plan_piper_speech,
    plan_rhubarb_lipsync,
)
from prompt_to_shot.renderers import (
    AssetPathError,
    Toolchain,
    plan_blender_render as renderers_plan_blender_render,
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


class AdaptersTestCase(unittest.TestCase):
    def setUp(self):
        # Resolve once so assertions match resolver output on symlinked temp dirs (macOS /var).
        root = Path(tempfile.mkdtemp(prefix="prompt-to-shot-adapters-")).resolve()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        self.root = root

    def touch(self, relative):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        return str(path)

    def ready_scene(self):
        self.touch("assets/voices/local_voice_01.onnx")
        return compile_scene(scene_payload())

    def fake_toolchain(self, available=(), filter_probe=None):
        paths = {name: f"/fake/bin/{name}" for name in available}
        return Toolchain(lookup=lambda name: paths.get(name), filter_probe=filter_probe)


class AdapterStatusTests(AdaptersTestCase):
    def test_reports_every_adapter_without_raising_when_tools_are_missing(self):
        chain = self.fake_toolchain(["ffmpeg"])

        report = adapter_status(chain)

        self.assertEqual(set(report["tools"]), set(ADAPTER_TOOLS))
        self.assertTrue(report["tools"]["ffmpeg"]["available"])
        self.assertEqual(report["tools"]["ffmpeg"]["path"], "/fake/bin/ffmpeg")
        self.assertFalse(report["tools"]["blender"]["available"])
        self.assertIsNone(report["tools"]["blender"]["path"])
        self.assertFalse(report["tools"]["piper"]["available"])
        self.assertIsNone(report["tools"]["piper"]["path"])
        self.assertFalse(report["tools"]["rhubarb"]["available"])
        self.assertIsNone(report["tools"]["rhubarb"]["path"])

    def test_reports_caption_capability_from_the_drawtext_filter_probe(self):
        supported = adapter_status(
            self.fake_toolchain(["ffmpeg"], filter_probe=lambda tool, name: True)
        )
        unsupported = adapter_status(
            self.fake_toolchain(["ffmpeg"], filter_probe=lambda tool, name: False)
        )

        self.assertEqual(supported["captions"], {"applied": True, "reason": None})
        self.assertFalse(unsupported["captions"]["applied"])
        self.assertIn("drawtext", unsupported["captions"]["reason"])

    def test_status_is_deterministic_and_json_safe(self):
        chain = self.fake_toolchain(
            ["ffmpeg", "blender"], filter_probe=lambda tool, name: False
        )

        first = adapter_status(chain)
        second = adapter_status(chain)

        self.assertEqual(first, second)
        self.assertEqual(first, json.loads(json.dumps(first)))


class PlanPiperSpeechTests(AdaptersTestCase):
    def test_plans_deterministic_tts_command_when_piper_is_available(self):
        scene = self.ready_scene()
        chain = self.fake_toolchain(["piper"])

        first = plan_piper_speech(scene, self.root, chain)
        second = plan_piper_speech(scene, self.root, chain)

        self.assertEqual(first, second)
        self.assertEqual(first, json.loads(json.dumps(first)))
        self.assertEqual(first["tool"], "piper")
        self.assertEqual(first["status"], "ready")
        self.assertTrue(first["applied"])
        self.assertIsNone(first["reason"])
        self.assertEqual(first["executable"], "/fake/bin/piper")
        argv = first["argv"]
        self.assertEqual(argv[0], "/fake/bin/piper")
        self.assertTrue(all(isinstance(arg, str) for arg in argv))
        self.assertEqual(
            argv[argv.index("--model") + 1],
            str(self.root / "assets" / "voices" / "local_voice_01.onnx"),
        )
        self.assertEqual(
            argv[argv.index("--output_file") + 1], str(self.root / "build" / "speech.wav")
        )
        self.assertEqual(
            first["assets"]["dialogue.voice_model"], argv[argv.index("--model") + 1]
        )
        self.assertEqual(first["missing_assets"], [])
        self.assertEqual(
            first["input"], {"kind": "stdin", "text": scene["dialogue"]["text"]}
        )
        self.assertEqual(first["voice"], "local_voice_01")
        self.assertEqual(first["output"]["path"], str(self.root / "build" / "speech.wav"))
        self.assertEqual(first["output"]["format"], "wav")
        self.assertEqual(first["output"]["path"], str(self.root / PIPER_OUTPUT_NAME))

    def test_reports_unavailable_status_and_keeps_scene_metadata_when_piper_is_missing(self):
        scene = self.ready_scene()

        plan = plan_piper_speech(scene, self.root, self.fake_toolchain([]))

        self.assertEqual(plan["status"], "unavailable")
        self.assertFalse(plan["applied"])
        self.assertIn("piper", plan["reason"])
        self.assertIsNone(plan["executable"])
        self.assertIsNone(plan["argv"])
        self.assertEqual(plan["input"], {"kind": "stdin", "text": scene["dialogue"]["text"]})
        self.assertEqual(plan["voice"], "local_voice_01")
        self.assertEqual(plan["output"]["path"], str(self.root / "build" / "speech.wav"))
        self.assertEqual(plan, json.loads(json.dumps(plan)))

    def test_reports_missing_voice_model_as_named_status(self):
        scene = compile_scene(scene_payload())

        plan = plan_piper_speech(scene, self.root, self.fake_toolchain(["piper"]))

        self.assertEqual(plan["status"], "missing_assets")
        self.assertTrue(plan["applied"])
        self.assertEqual(
            plan["missing_assets"],
            [
                {
                    "field": "dialogue.voice_model",
                    "path": str(self.root / "assets" / "voices" / "local_voice_01.onnx"),
                }
            ],
        )
        self.assertIn("--model", plan["argv"])

    def test_rejects_unsafe_voice_model_paths(self):
        scene = compile_scene(scene_payload())
        scene["dialogue"]["voice"] = "../evil"

        with self.assertRaises(AssetPathError) as ctx:
            plan_piper_speech(scene, self.root, self.fake_toolchain(["piper"]))

        self.assertIn("dialogue.voice_model", str(ctx.exception))

    def test_rejects_output_paths_that_escape_project_root(self):
        scene = self.ready_scene()

        with self.assertRaises(AssetPathError):
            plan_piper_speech(
                scene, self.root, self.fake_toolchain(["piper"]), output_name="../evil.wav"
            )


class PlanRhubarbLipsyncTests(AdaptersTestCase):
    def test_plans_deterministic_mouth_cue_command_when_rhubarb_is_available(self):
        scene = self.ready_scene()
        wav_path = self.touch("build/speech.wav")
        chain = self.fake_toolchain(["rhubarb"])

        first = plan_rhubarb_lipsync(scene, self.root, chain)
        second = plan_rhubarb_lipsync(scene, self.root, chain)

        self.assertEqual(first, second)
        self.assertEqual(first, json.loads(json.dumps(first)))
        self.assertEqual(first["tool"], "rhubarb")
        self.assertEqual(first["status"], "ready")
        self.assertTrue(first["applied"])
        self.assertIsNone(first["reason"])
        self.assertEqual(first["executable"], "/fake/bin/rhubarb")
        argv = first["argv"]
        self.assertEqual(argv[0], "/fake/bin/rhubarb")
        self.assertEqual(argv[argv.index("--exportFormat") + 1], "json")
        self.assertEqual(
            argv[argv.index("--output") + 1], str(self.root / "build" / "mouth-cues.json")
        )
        self.assertEqual(first["assets"]["dialogue.audio"], str(self.root / "build" / "speech.wav"))
        self.assertEqual(argv[-1], first["assets"]["dialogue.audio"])
        self.assertEqual(first["missing_assets"], [])
        self.assertEqual(first["text"], scene["dialogue"]["text"])
        self.assertEqual(first["voice"], "local_voice_01")
        self.assertEqual(first["lip_sync"], "rhubarb")
        self.assertEqual(
            first["output"],
            {"path": str(self.root / RHUBARB_OUTPUT_NAME), "format": "json"},
        )

    def test_reports_unavailable_status_and_keeps_paths_when_rhubarb_is_missing(self):
        scene = self.ready_scene()

        plan = plan_rhubarb_lipsync(scene, self.root, self.fake_toolchain([]))

        self.assertEqual(plan["status"], "unavailable")
        self.assertFalse(plan["applied"])
        self.assertIn("rhubarb", plan["reason"])
        self.assertIsNone(plan["executable"])
        self.assertIsNone(plan["argv"])
        self.assertEqual(
            plan["assets"]["dialogue.audio"], str(self.root / "build" / "speech.wav")
        )
        self.assertEqual(
            plan["output"]["path"], str(self.root / "build" / "mouth-cues.json")
        )
        self.assertEqual(plan, json.loads(json.dumps(plan)))

    def test_reports_missing_speech_wav_as_named_status(self):
        scene = self.ready_scene()

        plan = plan_rhubarb_lipsync(scene, self.root, self.fake_toolchain(["rhubarb"]))

        self.assertEqual(plan["status"], "missing_assets")
        self.assertTrue(plan["applied"])
        self.assertEqual(
            plan["missing_assets"],
            [
                {
                    "field": "dialogue.audio",
                    "path": str(self.root / "build" / "speech.wav"),
                }
            ],
        )
        self.assertIn("--exportFormat", plan["argv"])

    def test_does_not_apply_when_the_scene_requests_a_different_lip_sync(self):
        scene = self.ready_scene()
        scene["dialogue"]["lip_sync"] = "fluent"
        self.touch("build/speech.wav")

        plan = plan_rhubarb_lipsync(scene, self.root, self.fake_toolchain(["rhubarb"]))

        self.assertEqual(plan["status"], "ready")
        self.assertFalse(plan["applied"])
        self.assertIn("fluent", plan["reason"])
        self.assertEqual(plan["executable"], "/fake/bin/rhubarb")
        self.assertIsNone(plan["argv"])

    def test_rejects_unsafe_speech_and_output_paths(self):
        scene = self.ready_scene()

        for kwargs in (
            {"speech_path": "/etc/evil.wav"},
            {"output_name": "../evil.json"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(AssetPathError):
                plan_rhubarb_lipsync(
                    scene, self.root, self.fake_toolchain(["rhubarb"]), **kwargs
                )


class PlanBlenderAdapterTests(AdaptersTestCase):
    def test_exposes_the_renderers_blender_plan_when_blender_is_available(self):
        self.touch("assets/characters/lizard.blend")
        scene = self.ready_scene()
        chain = self.fake_toolchain(["blender"])
        expected = renderers_plan_blender_render(scene, self.root, chain)
        expected["applied"] = True
        expected["reason"] = None

        plan = plan_blender_render(scene, self.root, chain)

        self.assertEqual(plan, expected)
        self.assertEqual(plan, json.loads(json.dumps(plan)))

    def test_reports_unavailable_status_when_blender_is_missing(self):
        scene = self.ready_scene()

        plan = plan_blender_render(scene, self.root, self.fake_toolchain(["piper"]))

        self.assertEqual(plan["tool"], "blender")
        self.assertEqual(plan["status"], "unavailable")
        self.assertFalse(plan["applied"])
        self.assertIn("blender", plan["reason"])
        self.assertIsNone(plan["executable"])
        self.assertIsNone(plan["argv"])
        self.assertIsNone(plan["output"])
        self.assertEqual(plan, json.loads(json.dumps(plan)))

    def test_reports_missing_character_asset_through_the_wrapper(self):
        scene = compile_scene(scene_payload())
        scene["character"]["asset"] = "assets/characters/missing.blend"

        plan = plan_blender_render(scene, self.root, self.fake_toolchain(["blender"]))

        self.assertEqual(plan["status"], "missing_assets")
        self.assertTrue(plan["applied"])
        self.assertIsNone(plan["reason"])
        self.assertEqual(
            [entry["field"] for entry in plan["missing_assets"]], ["character.asset"]
        )


if __name__ == "__main__":
    unittest.main()
