import unittest


class HttpContractTests(unittest.TestCase):
    def test_authenticated_request_accepts_only_the_existing_queue_message(self):
        from worker.http_contract import authenticate_render_request

        self.assertEqual(
            authenticate_render_request(b'{"renderJobId":"rj_123"}', "Bearer shared-secret", "shared-secret"),
            "rj_123",
        )
        with self.assertRaises(PermissionError):
            authenticate_render_request(b'{"renderJobId":"rj_123"}', "Bearer wrong", "shared-secret")
        with self.assertRaises(ValueError):
            authenticate_render_request(b'{"jobId":"rj_123"}', "Bearer shared-secret", "shared-secret")

    def test_dispatch_starts_the_render_without_holding_the_queue_request_open(self):
        from worker.service import dispatch_render_job

        started = []

        class Thread:
            def __init__(self, *, target, args, daemon):
                self.target, self.args, self.daemon = target, args, daemon
            def start(self):
                started.append((self.target, self.args, self.daemon))

        result = dispatch_render_job("rj_123", object(), thread_class=Thread)
        self.assertEqual(result, {"accepted": True, "jobId": "rj_123"})
        self.assertEqual(started[0][1][0], "rj_123")
        self.assertTrue(started[0][2])


if __name__ == "__main__":
    unittest.main()
