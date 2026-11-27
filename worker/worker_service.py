"""Coordinates one PHOTO_UPLOADED event from Pub/Sub to GCS and Backend API."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from event_contract import UUID_PATTERN

from processors.image_processor import InvalidImageError, create_thumbnails
from services.gcs_service import OriginalTooLargeError, SourceObjectNotFound

logger = logging.getLogger(__name__)
_SUPPORTED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}


class PermanentMessageError(Exception):
    """The event/image cannot succeed by retrying; ACK after status is recorded."""


class PhotoWorker:
    def __init__(self, storage, status_client, *, max_image_pixels: int = 40_000_000) -> None:
        self.storage = storage
        self.status_client = status_client
        self.max_image_pixels = max_image_pixels

    @staticmethod
    def _log_terminal(event: dict, result: dict | None, status: str) -> None:
        if not result or not result.get("terminalCommit"):
            return
        photo_id = event["photoId"]
        record = {"event": "job_terminal", "photoId": photo_id, "jobId": result.get("jobId") or event.get("jobId", photo_id), "status": status}
        if event.get("createdAt"):
            created_at = datetime.fromisoformat(event["createdAt"].replace("Z", "+00:00"))
            record["latencySeconds"] = max(0, (datetime.now(timezone.utc) - created_at).total_seconds())
        print(json.dumps(record), flush=True)

    def _mark_failed(self, event: dict, photo_id: str, reason: str) -> None:
        # If the Backend update fails, let the exception escape so Pub/Sub redelivers.
        result = self.status_client.update(photo_id, {
            "status": "FAILED",
            "progress": 0,
            "errorMessage": reason[:500],
        })
        self._log_terminal(event, result, "FAILED")

    def process(self, event: dict) -> dict[str, str]:
        photo_id = str(event.get("photoId", "")).lower()
        if not UUID_PATTERN.fullmatch(photo_id):
            raise PermanentMessageError("photoId is not a valid PostgreSQL UUID")

        result = self.status_client.update(photo_id, {"status": "PROCESSING", "progress": 10})
        if result and result.get("alreadyTerminal"):
            return {}

        mime_type = event.get("mimeType")
        if mime_type not in _SUPPORTED_MIME_TYPES:
            reason = f"Unsupported MIME type: {mime_type!r}"
            self._mark_failed(event, photo_id, reason)
            raise PermanentMessageError(reason)

        bucket = event["bucket"]
        original_object = event["originalObject"]
        small_key = f"thumbnails/{photo_id}/small.webp"
        large_key = f"thumbnails/{photo_id}/large.webp"

        try:
            original_bytes = self.storage.download_original(bucket, original_object)
        except (SourceObjectNotFound, OriginalTooLargeError) as exc:
            self._mark_failed(event, photo_id, str(exc))
            raise PermanentMessageError(str(exc)) from exc

        self.status_client.update(photo_id, {"status": "PROCESSING", "progress": 35})
        try:
            small, large = create_thumbnails(
                original_bytes,
                expected_mime_type=mime_type,
                max_pixels=self.max_image_pixels,
            )
        except InvalidImageError as exc:
            self._mark_failed(event, photo_id, str(exc))
            raise PermanentMessageError(str(exc)) from exc

        # GCS create-only writes make redelivery safe. Existing deterministic outputs
        # are validated by GCSImageStorage before being reused.
        self.storage.save_thumbnail(bucket, small_key, small)
        self.storage.save_thumbnail(bucket, large_key, large)

        self.status_client.update(photo_id, {"status": "PROCESSING", "progress": 90})
        result = self.status_client.update(photo_id, {
            "status": "COMPLETED",
            "progress": 100,
            "thumbnailObject": large_key,
            "thumbnailSmallObject": small_key,
            "thumbnailLargeObject": large_key,
        })
        self._log_terminal(event, result, "COMPLETED")

        logger.info("Processed photo %s: small=%s large=%s", photo_id, small_key, large_key)
        return {"small": small_key, "large": large_key}
