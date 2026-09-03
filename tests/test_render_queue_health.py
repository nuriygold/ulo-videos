import importlib.util
import io
import json
import unittest
from pathlib import Path


ENTRY = Path(__file__).resolve().parents[1] / "api" / "render-queue.py"


class RenderQueueHealthTests(unittest.TestCase):
    def test_queue_health_is_unauthenticated_and_describes_the_fallback(self):
        spec = importlib.util.spec_from_file_location("render_queue_health", ENTRY)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        body = b"".join(module.app({"REQUEST_METHOD": "GET", "wsgi.input": io.BytesIO()}, start_response))
        self.assertEqual(captured["status"], "200 OK")
        self.assertEqual(json.loads(body), {
            "ok": True,
            "mode": "vercel_fallback",
            "capabilities": {"freezeResume": True, "logo": True, "captions": True, "character": False, "sourceAudio": False, "speech": False, "lipSync": False, "characterFormats": []},
        })


if __name__ == "__main__":
    unittest.main()
