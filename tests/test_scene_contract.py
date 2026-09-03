import math
import unittest

from ulo_videos.scene_contract import SceneContractError, normalize_scene


def legacy_scene():
    return {
        "template": "interruption_spokescharacter_v1",
        "background_video": "assets/house_leak.mp4",
        "pause_at": 7.4,
        "character": {"asset": "assets/lizard.blend", "position": "foreground_right", "entrance": "pop_in", "gesture": "shrug_and_point"},
        "dialogue": {"text": "Hi", "voice": "voice_01", "lip_sync": "rhubarb"},
        "branding": {"logo": "assets/logo.svg", "caption_style": "lower_third"},
        "output": {"resolution": [1920, 1080], "fps": 30, "format": "mp4"},
    }


class SceneContractTests(unittest.TestCase):
    def test_normalizes_legacy_scene_to_generic_contract(self):
        scene = normalize_scene(legacy_scene())
        self.assertEqual(scene["version"], 1)
        self.assertEqual(scene["source"], {"video": "assets/house_leak.mp4"})
        self.assertEqual(scene["trigger"], {"type": "timestamp", "value": 7.4})
        self.assertEqual(scene["elements"][0]["performance"], {"gesture": "shrug_and_point"})

    def test_rejects_non_finite_trigger_values(self):
        scene = legacy_scene()
        scene["pause_at"] = math.nan
        with self.assertRaisesRegex(SceneContractError, "finite"):
            normalize_scene(scene)

    def test_rejects_unknown_presets(self):
        scene = legacy_scene()
        scene["character"]["gesture"] = "invented"
        with self.assertRaisesRegex(SceneContractError, "gesture"):
            normalize_scene(scene)

