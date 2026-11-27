"""Validated environment configuration for the Cloud Photo Gallery worker."""
from __future__ import annotations

from dataclasses import dataclass
import os
from urllib.parse import urlsplit

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    gcp_project_id: str
    gcs_bucket_name: str
    pubsub_topic: str
    pubsub_subscription: str
    api_base_url: str
    worker_shared_secret: str
    api_timeout_seconds: int
    max_messages: int
    max_original_bytes: int
    max_image_pixels: int
    shutdown_grace_seconds: int


def _positive_int(name: str, default: str, *, minimum: int = 1, maximum: int = 2_147_483_647) -> int:
    raw = os.getenv(name, default).strip()
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


def _validate_api_url(value: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError("BACKEND_API_BASE_URL must be a valid http(s) URL")
    if parsed.username or parsed.password:
        raise RuntimeError("BACKEND_API_BASE_URL must not contain embedded credentials")
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and parsed.hostname not in local_hosts:
        raise RuntimeError("BACKEND_API_BASE_URL must use HTTPS outside localhost")
    if parsed.query or parsed.fragment:
        raise RuntimeError("BACKEND_API_BASE_URL must not contain a query string or fragment")
    return value


def load_settings(*, push: bool = False) -> Settings:
    """Load .env and validate all configuration before opening cloud clients."""
    load_dotenv()
    required = [
        "GCP_PROJECT_ID",
        "GCS_BUCKET_NAME",
        "WORKER_SHARED_SECRET",
    ]
    if not push:
        required.extend(["PUBSUB_TOPIC", "PUBSUB_SUBSCRIPTION"])
    missing = [name for name in required if not os.getenv(name, "").strip()]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    secret = os.environ["WORKER_SHARED_SECRET"].strip()
    if len(secret) < 32:
        raise RuntimeError("WORKER_SHARED_SECRET must contain at least 32 characters")

    project_id = os.environ["GCP_PROJECT_ID"].strip()
    bucket_name = os.environ["GCS_BUCKET_NAME"].strip()
    topic = os.getenv("PUBSUB_TOPIC", "").strip()
    subscription = os.getenv("PUBSUB_SUBSCRIPTION", "").strip()
    if any(ch.isspace() for ch in project_id):
        raise RuntimeError("GCP_PROJECT_ID must not contain whitespace")
    if any(ch.isspace() for ch in bucket_name):
        raise RuntimeError("GCS_BUCKET_NAME must not contain whitespace")
    if any(ch.isspace() for ch in topic):
        raise RuntimeError("PUBSUB_TOPIC must not contain whitespace")
    if any(ch.isspace() for ch in subscription):
        raise RuntimeError("PUBSUB_SUBSCRIPTION must not contain whitespace")

    api_base_url = _validate_api_url(
        os.getenv("BACKEND_BASE_URL") or os.getenv("BACKEND_API_BASE_URL", "http://localhost:3000")
    )

    return Settings(
        gcp_project_id=project_id,
        gcs_bucket_name=bucket_name,
        pubsub_topic=topic,
        pubsub_subscription=subscription,
        api_base_url=api_base_url,
        worker_shared_secret=secret,
        api_timeout_seconds=_positive_int("API_TIMEOUT_SECONDS", "15", maximum=120),
        max_messages=_positive_int("MAX_MESSAGES", "1", maximum=100),
        max_original_bytes=_positive_int("MAX_ORIGINAL_BYTES", str(10 * 1024 * 1024), maximum=100 * 1024 * 1024),
        max_image_pixels=_positive_int("MAX_IMAGE_PIXELS", "25000000", maximum=200_000_000),
        shutdown_grace_seconds=_positive_int("SHUTDOWN_GRACE_SECONDS", "30", maximum=300),
    )
