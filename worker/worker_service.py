"""Coordinates one PHOTO_UPLOADED event from Pub/Sub to GCS and Backend API."""
from __future__ import annotations

import logging
import re

from processors.image_processor import InvalidImageError, create_thumbnails
from services.gcs_service import OriginalTooLargeError, SourceObjectNotFound

logger = logging.getLogger(__name__)
_PHOTO_ID_PATTERN = re.compile(r"^[a-f0-9]{24}$")
_SUPPORTED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}


class PermanentMessageError(Exception):
    """The event/image cannot succeed by retrying; ACK after status is recorded."""


class PhotoWorker:
    def __init__(self, storage, status_client, *, max_image_pixels: int = 40_000_000) -> None:
        self.storage = storage
        self.status_client = status_client
        self.max_image_pixels = max_image_pixels

    def _mark_failed(self, photo_id: str, reason: str) -> None:
        # If the Backend update fails, let the exception escape so Pub/Sub redelivers.
        self.status_client.update(photo_id, {
            "status": "FAILED",
            "progress": 0,
            "errorMessage": reason[:500],
        })

    def process(self, event: dict) -> dict[str, str]:
        photo_id = str(event.get("photoId", "")).lower()
        if not _PHOTO_ID_PATTERN.fullmatch(photo_id):
            raise PermanentMessageError("photoId is not a valid MongoDB ObjectId")

        mime_type = event.get("mimeType")
        if mime_type not in _SUPPORTED_MIME_TYPES:
            reason = f"Unsupported MIME type: {mime_type!r}"
            self._mark_failed(photo_id, reason)
            raise PermanentMessageError(reason)

        bucket = event["bucket"]
        original_object = event["originalObject"]
        small_key = f"thumbnail/small/{photo_id}.webp"
        large_key = f"thumbnail/large/{photo_id}.webp"

        self.status_client.update(photo_id, {"status": "PROCESSING", "progress": 10})
        try:
            original_bytes = self.storage.download_original(bucket, original_object)
        except (SourceObjectNotFound, OriginalTooLargeError) as exc:
            self._mark_failed(photo_id, str(exc))
            raise PermanentMessageError(str(exc)) from exc

        self.status_client.update(photo_id, {"status": "PROCESSING", "progress": 35})
        try:
            small, large = create_thumbnails(
                original_bytes,
                expected_mime_type=mime_type,
                max_pixels=self.max_image_pixels,
            )
        except InvalidImageError as exc:
            self._mark_failed(photo_id, str(exc))
            raise PermanentMessageError(str(exc)) from exc

        # GCS create-only writes make redelivery safe. Existing deterministic outputs
        # are validated by GCSImageStorage before being reused.
        self.storage.save_thumbnail(bucket, small_key, small)
        self.storage.save_thumbnail(bucket, large_key, large)

        self.status_client.update(photo_id, {"status": "PROCESSING", "progress": 90})
        # Member 2's existing Photo model/API supports only `thumbnailObject`.
        # Store the large thumbnail there without changing the shared Backend contract.
        self.status_client.update(photo_id, {
            "status": "COMPLETED",
            "progress": 100,
            "thumbnailObject": large_key,
        })

        logger.info("Processed photo %s: small=%s large=%s", photo_id, small_key, large_key)
        return {"small": small_key, "large": large_key}
