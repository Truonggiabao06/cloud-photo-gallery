import unittest
from unittest.mock import Mock

from config import Settings
from services.status_api import WorkerStatusClient


class FakeResponse:
    def __init__(self, ok=True, status_code=200, text=""):
        self.ok = ok
        self.status_code = status_code
        self.text = text


class StatusApiTests(unittest.TestCase):
    def make_settings(self):
        return Settings(
            gcp_project_id="project",
            gcs_bucket_name="bucket",
            pubsub_topic="topic",
            pubsub_subscription="subscription",
            api_base_url="http://localhost:3000",
            worker_shared_secret="x" * 40,
            api_timeout_seconds=9,
            max_messages=1,
            max_original_bytes=10_000,
            max_image_pixels=25_000_000,
            shutdown_grace_seconds=30,
        )

    def test_calls_exact_member2_endpoint_and_secret_header(self):
        session = Mock()
        session.headers = {}
        session.patch.return_value = FakeResponse()
        client = WorkerStatusClient(self.make_settings(), session=session)
        client.update("01234567-89ab-cdef-0123-456701234567", {"status": "PROCESSING", "progress": 10})
        self.assertEqual(session.headers["x-worker-secret"], "x" * 40)
        args, kwargs = session.patch.call_args
        self.assertEqual(
            args[0],
            "http://localhost:3000/api/photos/01234567-89ab-cdef-0123-456701234567/worker-status",
        )
        self.assertEqual(kwargs["json"], {"status": "PROCESSING", "progress": 10})
        self.assertEqual(kwargs["timeout"], 9)
        self.assertFalse(kwargs["allow_redirects"])

    def test_non_2xx_response_raises(self):
        session = Mock()
        session.headers = {}
        session.patch.return_value = FakeResponse(ok=False, status_code=401, text="unauthorized")
        client = WorkerStatusClient(self.make_settings(), session=session)
        with self.assertRaisesRegex(RuntimeError, "HTTP 401"):
            client.update("01234567-89ab-cdef-0123-456701234567", {"status": "FAILED"})

    def test_redirect_is_not_treated_as_success(self):
        session = Mock()
        session.headers = {}
        session.patch.return_value = FakeResponse(ok=True, status_code=302, text="redirect")
        client = WorkerStatusClient(self.make_settings(), session=session)
        with self.assertRaisesRegex(RuntimeError, "HTTP 302"):
            client.update("01234567-89ab-cdef-0123-456701234567", {"status": "PROCESSING"})


if __name__ == "__main__":
    unittest.main()
