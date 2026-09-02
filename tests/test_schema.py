import json
import unittest

from prompt_to_shot.schema import SceneValidationError
from prompt_to_shot.templates import compile_scene, serialize_scene


def valid_payload():
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
        "branding": {
            "logo": "assets/logo.svg",
            "caption_style": "lower_third",
        },
        "output": {"resolution": [1920, 1080]},
    }


class SceneSchemaTests(unittest.TestCase):
    def test_compiles_and_applies_output_defaults(self):
        scene = compile_scene(valid_payload())

        self.assertEqual(scene["output"], {
            "format": "mp4",
            "resolution": [1920, 1080],
            "fps": 30,
        })
        self.assertEqual(scene["character"]["gesture"], "shrug_and_point")
        self.assertEqual(scene["dialogue"]["text"], valid_payload()["dialogue"]["text"])
        self.assertEqual(scene["branding"]["caption_style"], "lower_third")

    def test_rejects_missing_required_fields(self):
        for field in ("template", "background_video", "pause_at", "character", "dialogue", "branding", "output"):
            payload = valid_payload()
            del payload[field]
            with self.subTest(field=field), self.assertRaises(SceneValidationError):
                compile_scene(payload)

    def test_rejects_missing_required_nested_values(self):
        for parent, child in (
            ("character", "asset"),
            ("character", "gesture"),
            ("dialogue", "text"),
            ("dialogue", "voice"),
            ("branding", "logo"),
            ("branding", "caption_style"),
            ("output", "resolution"),
        ):
            payload = valid_payload()
            del payload[parent][child]
            with self.subTest(parent=parent, child=child), self.assertRaises(SceneValidationError):
                compile_scene(payload)

    def test_rejects_non_numeric_or_negative_pause(self):
        for pause_at in ("7.4", -0.1, True):
            payload = valid_payload()
            payload["pause_at"] = pause_at
            with self.subTest(pause_at=pause_at), self.assertRaises(SceneValidationError):
                compile_scene(payload)

    def test_serializes_with_sorted_keys_and_stable_indentation(self):
        first = serialize_scene(compile_scene(valid_payload()))
        second = serialize_scene(compile_scene(valid_payload()))

        self.assertEqual(first, second)
        self.assertEqual(json.loads(first), compile_scene(valid_payload()))
        self.assertLess(first.index('"background_video"'), first.index('"template"'))
        self.assertIn("\n  \"background_video\"", first)


if __name__ == "__main__":
    unittest.main()
