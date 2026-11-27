"""Run a Render HTTP service and one background Outbox consumer per instance."""

import hmac
import logging
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass

from dotenv import load_dotenv
from flask import Flask, request

from config import _positive_int, _validate_api_url
from services.outbox import Outbox
from services.s3_service import S3ImageStorage
from services.status_api import WorkerStatusClient
from worker_service import PhotoWorker

logger = logging.getLogger(__name__)


def create_app():
    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    bucket = os.getenv("S3_BUCKET")
    secret = os.getenv("WORKER_SHARED_SECRET", "")
    if not database_url or not bucket or len(secret) < 32:
        raise RuntimeError("DATABASE_URL, S3_BUCKET and a 32-character WORKER_SHARED_SECRET are required")
    settings = Settings(
        _validate_api_url(os.getenv("BACKEND_BASE_URL", "http://127.0.0.1:3000")),
        _positive_int("API_TIMEOUT_SECONDS", "15", maximum=30),
        secret,
    )
    poll_seconds = _positive_int("OUTBOX_POLL_SECONDS", "20", minimum=5, maximum=60)
    store = S3ImageStorage(
        max_original_bytes=_positive_int("MAX_ORIGINAL_BYTES", "10485760", maximum=10485760)
    )
    pixel_limit = _positive_int("MAX_IMAGE_PIXELS", "25000000", maximum=40000000)
    outbox = Outbox(database_url, bucket)
    wake = threading.Event()
    heartbeat = None

    @contextmanager
    def make_worker(lease_id, before_write):
        status_client = WorkerStatusClient(settings, lease_id=lease_id)
        try:
            yield PhotoWorker(store, status_client, max_image_pixels=pixel_limit, before_write=before_write)
        finally:
            status_client.session.close()

    def poll():
        nonlocal heartbeat
        while True:
            try:
                with outbox.connect() as db:
                    db.execute("SET statement_timeout = 5000")
                    while True:
                        wake.clear()
                        db.execute("SELECT 1")
                        heartbeat = time.monotonic()
                        if not outbox.process_one(db, make_worker):
                            wake.wait(poll_seconds)
            except Exception as error:
                heartbeat = None
                logger.warning("Outbox connection or delivery interrupted: %s", type(error).__name__)
                time.sleep(5)

    thread = threading.Thread(target=poll, name="photo-outbox", daemon=True)
    thread.start()
    app = Flask(__name__)

    @app.get("/health")
    def health():
        if thread.is_alive() and heartbeat is not None and time.monotonic() - heartbeat < 180:
            return {"status": "OK"}
        return {"status": "unavailable"}, 503

    @app.post("/wake")
    def wake_worker():
        supplied = request.headers.get("x-worker-secret", "").encode()
        if not hmac.compare_digest(supplied, secret.encode()):
            return "", 401
        wake.set()
        return "", 202

    return app


@dataclass(frozen=True)
class Settings:
    api_base_url: str
    api_timeout_seconds: int
    worker_shared_secret: str
