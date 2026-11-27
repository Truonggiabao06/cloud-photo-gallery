import base64
import json
import unittest
from unittest.mock import Mock, patch

from config import load_settings
from push_app import create_app
from worker_service import PermanentMessageError


class PushAppTests(unittest.TestCase):
    def setUp(self):
        self.worker = Mock()
        self.client = create_app(worker=self.worker, bucket="test-bucket").test_client()
        self.event = {
            "eventType": "PHOTO_UPLOADED",
            "eventVersion": 1,
            "photoId": "a" * 24,
            "albumId": "b" * 24,
            "userId": "local-user",
            "bucket": "test-bucket",
            "originalObject": "original/local-user/" + "b" * 24 + "/test.jpg",
            "mimeType": "image/jpeg",
            "createdAt": "2026-01-01T00:00:00Z",
        }

    def post(self, event=None):
        encoded = base64.b64encode(json.dumps(event or self.event).encode()).decode()
        return self.client.post("/pubsub/push", json={"message": {"messageId": "123", "data": encoded}})

    def test_startup_uses_terraform_environment_without_pull_subscription(self):
        with patch.dict("os.environ", {
            "GCP_PROJECT_ID": "test-project",
            "GCS_BUCKET_NAME": "test-bucket",
            "WORKER_SHARED_SECRET": "x" * 32,
            "BACKEND_BASE_URL": "https://backend.example",
        }, clear=True):
            self.assertEqual(load_settings(push=True).api_base_url, "https://backend.example")
            with self.assertRaises(RuntimeError):
                load_settings()

    def test_health(self):
        self.assertEqual(self.client.get("/healthz").get_json(), {"status": "OK"})

    def test_success_acks_after_processing(self):
        self.assertEqual(self.post().status_code, 204)
        self.worker.process.assert_called_once()
        self.assertEqual(self.worker.process.call_args.args[0]["photoId"], "a" * 24)

    def test_permanent_failure_acks(self):
        self.worker.process.side_effect = PermanentMessageError("invalid JPEG")
        self.assertEqual(self.post().status_code, 204)

    def test_transient_failure_retries(self):
        self.worker.process.side_effect = OSError("storage retry")
        self.assertEqual(self.post().status_code, 503)

    def test_bucket_mismatch_retries(self):
        self.assertEqual(self.post({**self.event, "bucket": "wrong-bucket"}).status_code, 503)
        self.worker.process.assert_not_called()

    def test_bad_wrap_and_base64_rejected(self):
        self.assertEqual(self.client.post("/pubsub/push", json={}).status_code, 400)
        bad = {"message": {"messageId":"123", "data":"..??"}}
        self.assertEqual(self.client.post("/pubsub/push", json=bad).status_code, 400)
        self.worker.process.assert_not_called()

    def test_terraform_custom_path(self):
        client = create_app(worker=self.worker, bucket="test-bucket", push_path="/events/photo").test_client()
        self.assertEqual(client.post("/pubsub/push").status_code, 404)
        self.assertEqual(client.post("/events/photo", json={}).status_code, 400)
