import os
import unittest
from unittest.mock import patch

from config import load_settings


BASE_ENV = {
    "GCP_PROJECT_ID": "demo-project-123",
    "GCS_BUCKET_NAME": "gallery-private-bucket",
    "PUBSUB_TOPIC": "photo-processing",
    "PUBSUB_SUBSCRIPTION": "photo-processing-worker",
    "WORKER_SHARED_SECRET": "a-random-secret-with-more-than-32-characters",
    "BACKEND_API_BASE_URL": "http://localhost:3000",
}


class ConfigTests(unittest.TestCase):
    def test_loads_required_settings_and_defaults(self):
        with patch.dict(os.environ, BASE_ENV, clear=True):
            settings = load_settings()
        self.assertEqual(settings.gcs_bucket_name, "gallery-private-bucket")
        self.assertEqual(settings.pubsub_topic, "photo-processing")
        self.assertEqual(settings.max_messages, 1)
        self.assertEqual(settings.max_original_bytes, 10 * 1024 * 1024)

    def test_requires_bucket_and_secret(self):
        env = dict(BASE_ENV)
        env.pop("GCS_BUCKET_NAME")
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "GCS_BUCKET_NAME"):
                load_settings()

    def test_requires_long_shared_secret(self):
        env = dict(BASE_ENV)
        env["WORKER_SHARED_SECRET"] = "short"
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "at least 32"):
                load_settings()

    def test_rejects_insecure_remote_backend_http(self):
        env = dict(BASE_ENV)
        env["BACKEND_API_BASE_URL"] = "http://backend.example.com"
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "HTTPS"):
                load_settings()

    def test_accepts_https_remote_backend(self):
        env = dict(BASE_ENV)
        env["BACKEND_API_BASE_URL"] = "https://api.example.com/"
        with patch.dict(os.environ, env, clear=True):
            settings = load_settings()
        self.assertEqual(settings.api_base_url, "https://api.example.com")


if __name__ == "__main__":
    unittest.main()
