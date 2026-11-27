"""HTTP entry point for authenticated Pub/Sub push on private Cloud Run."""

import base64
import binascii
import os

from flask import Flask, request

from config import load_settings
from main import handle_message
from services.gcs_service import GCSImageStorage
from services.status_api import WorkerStatusClient
from worker_service import PhotoWorker


class PushMessage:
    """Provide the ack/nack interface used by the existing event handler."""

    def __init__(self, data: bytes, message_id: str, delivery_attempt: int):
        self.data = data
        self.message_id = message_id
        self.delivery_attempt = delivery_attempt
        self.acknowledged = False

    def ack(self) -> None:
        self.acknowledged = True

    def nack(self) -> None:
        self.acknowledged = False


def create_app(*, worker=None, bucket=None, push_path=None):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024

    if worker is None:
        settings = load_settings(push=True)
        bucket = settings.gcs_bucket_name
        worker = PhotoWorker(
            GCSImageStorage(max_original_bytes=settings.max_original_bytes),
            WorkerStatusClient(settings),
            max_image_pixels=settings.max_image_pixels,
        )
    push_path = push_path or os.getenv("PUBSUB_PUSH_PATH", "/pubsub/push")

    @app.get("/healthz")
    def health():
        return {"status": "OK"}

    @app.post(push_path)
    def receive_push():
        # Cloud Run IAM authenticates the OIDC caller before routing here.
        envelope = request.get_json(silent=True)
        if not isinstance(envelope, dict) or not isinstance(envelope.get("message"), dict):
            return {"error": "Expected a wrapped Pub/Sub message"}, 400
        message = envelope["message"]
        encoded = message.get("data")
        message_id = message.get("messageId") or message.get("message_id")
        if not isinstance(encoded, str) or not isinstance(message_id, str) or not message_id:
            return {"error": "Expected message.data and messageId"}, 400
        if not message_id.isascii() or not message_id.isdigit() or len(message_id) > 40:
            return {"error": "Invalid Pub/Sub message ID"}, 400
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            return {"error": "Invalid Pub/Sub data encoding"}, 400

        attempt = envelope.get("deliveryAttempt")
        delivery = PushMessage(decoded, message_id, attempt if type(attempt) is int and attempt >= 1 else 1)
        handle_message(delivery, worker, bucket)
        if delivery.acknowledged:
            return "", 204
        return {"error": "Worker could not complete this delivery"}, 503

    return app
