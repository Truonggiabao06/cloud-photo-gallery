"""Validation for Member 2's PHOTO_UPLOADED Pub/Sub event contract."""
from __future__ import annotations

from datetime import datetime
import re
from typing import Any


UUID_PATTERN = re.compile(r"^[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}$")
_REQUIRED_FIELDS = (
    "eventType",
    "eventVersion",
    "photoId",
    "albumId",
    "userId",
    "bucket",
    "originalObject",
    "mimeType",
    "createdAt",
)


class InvalidEventError(ValueError):
    """The payload violates the documented event contract and should not be retried."""


class BucketConfigurationError(RuntimeError):
    """The event bucket and Worker configuration disagree; retry after fixing config."""


def validate_event(payload: Any, expected_bucket: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise InvalidEventError("Pub/Sub message JSON must be an object")

    missing = [name for name in _REQUIRED_FIELDS if name not in payload]
    if missing:
        raise InvalidEventError(f"Missing required fields: {', '.join(missing)}")

    if not isinstance(payload["eventType"], str) or payload["eventType"] != "PHOTO_UPLOADED":
        raise InvalidEventError(f"Unsupported eventType: {payload['eventType']!r}")
    if type(payload["eventVersion"]) is not int or payload["eventVersion"] != 1:
        raise InvalidEventError("eventVersion must be integer 1")

    photo_id = payload["photoId"]
    album_id = payload["albumId"]
    if not isinstance(photo_id, str) or not UUID_PATTERN.fullmatch(photo_id):
        raise InvalidEventError("photoId must be a PostgreSQL UUID")
    if not isinstance(album_id, str) or not UUID_PATTERN.fullmatch(album_id):
        raise InvalidEventError("albumId must be a PostgreSQL UUID")

    job_id = payload.get("jobId", photo_id)
    if not isinstance(job_id, str) or not UUID_PATTERN.fullmatch(job_id):
        raise InvalidEventError("jobId must be a PostgreSQL UUID")

    user_id = payload["userId"]
    if (
        not isinstance(user_id, str)
        or not user_id.strip()
        or len(user_id) > 512
        or user_id != user_id.strip()
        or "/" in user_id
        or "\\" in user_id
        or user_id in {".", ".."}
    ):
        raise InvalidEventError("userId is empty or contains unsafe path characters")

    bucket = payload["bucket"]
    if not isinstance(bucket, str) or not bucket.strip():
        raise InvalidEventError("bucket must be a non-empty string")
    if bucket != expected_bucket:
        raise BucketConfigurationError(
            "Event bucket does not match GCS_BUCKET_NAME; check Member 2 and Worker configuration"
        )

    object_name = payload["originalObject"]
    if not isinstance(object_name, str) or not object_name or len(object_name) > 1024:
        raise InvalidEventError("originalObject must be a non-empty object key")
    if object_name.startswith("/") or "\\" in object_name:
        raise InvalidEventError("originalObject contains an unsafe path")
    parts = object_name.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise InvalidEventError("originalObject contains an unsafe path segment")
    expected_prefix = f"original/{user_id}/{album_id}/"
    if not object_name.startswith(expected_prefix) or len(parts) != 4:
        raise InvalidEventError("originalObject does not match the Backend original/<userId>/<albumId>/<file> layout")

    mime_type = payload["mimeType"]
    if not isinstance(mime_type, str) or not mime_type.strip():
        raise InvalidEventError("mimeType must be a non-empty string")

    created_at = payload["createdAt"]
    if not isinstance(created_at, str) or not created_at:
        raise InvalidEventError("createdAt must be an ISO-8601 timestamp")
    try:
        parsed_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidEventError("createdAt must be a valid ISO-8601 timestamp") from exc
    if parsed_time.tzinfo is None:
        raise InvalidEventError("createdAt must include a timezone")

    # Return a new, normalized mapping rather than mutating Pub/Sub's decoded object.
    return {
        "eventType": "PHOTO_UPLOADED",
        "eventVersion": 1,
        "photoId": photo_id.lower(),
        "jobId": job_id.lower(),
        "albumId": album_id.lower(),
        "userId": user_id,
        "bucket": bucket,
        "originalObject": object_name,
        "mimeType": mime_type,
        "createdAt": created_at,
    }
