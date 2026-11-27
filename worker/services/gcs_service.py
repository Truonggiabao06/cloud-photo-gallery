"""Google Cloud Storage adapter with bounded downloads and create-only writes."""
from __future__ import annotations

import logging
from io import BytesIO

from PIL import Image, UnidentifiedImageError

from processors.image_processor import Thumbnail

logger = logging.getLogger(__name__)


class SourceObjectNotFound(Exception):
    """The original object referenced by a valid event does not exist."""


class OriginalTooLargeError(Exception):
    """The original object exceeds the Backend's configured upload limit."""


class GCSImageStorage:
    def __init__(self, *, max_original_bytes: int, client=None) -> None:
        self.max_original_bytes = max_original_bytes
        if client is None:
            # Lazy import keeps unit tests runnable without cloud credentials/packages.
            from google.cloud import storage
            client = storage.Client()
        self.client = client

    @staticmethod
    def _is_error(exc: Exception, *, name: str, code: int) -> bool:
        response_code = getattr(exc, "code", None)
        if callable(response_code):
            try:
                response_code = response_code()
            except Exception:
                response_code = None
        return exc.__class__.__name__ == name or response_code == code

    def download_original(self, bucket_name: str, object_name: str) -> bytes:
        if not bucket_name or not object_name:
            raise ValueError("bucket and originalObject are required")
        blob = self.client.bucket(bucket_name).blob(object_name)
        try:
            blob.reload()
        except Exception as exc:
            if self._is_error(exc, name="NotFound", code=404):
                raise SourceObjectNotFound(
                    f"Original image object was not found: gs://{bucket_name}/{object_name}"
                ) from exc
            raise

        if blob.size is not None and int(blob.size) > self.max_original_bytes:
            raise OriginalTooLargeError(
                f"Original image exceeds the {self.max_original_bytes:,}-byte processing limit"
            )

        # Pin the generation so metadata validation and download refer to the same object.
        generation = getattr(blob, "generation", None)
        if generation is None:
            data = blob.download_as_bytes()
        else:
            data = blob.download_as_bytes(if_generation_match=int(generation))
        if len(data) > self.max_original_bytes:
            raise OriginalTooLargeError(
                f"Original image exceeds the {self.max_original_bytes:,}-byte processing limit"
            )
        return data

    def save_thumbnail(self, bucket_name: str, object_name: str, thumbnail: Thumbnail) -> bool:
        """Create a thumbnail once; return False when a valid deterministic object exists."""
        blob = self.client.bucket(bucket_name).blob(object_name)
        try:
            blob.upload_from_string(
                thumbnail.data,
                content_type=thumbnail.content_type,
                if_generation_match=0,
                checksum="auto",
                timeout=60,
            )
            logger.info("Created gs://%s/%s", bucket_name, object_name)
            return True
        except Exception as exc:
            # GCS returns HTTP 412 when a generation-0 create targets an existing object.
            if not self._is_error(exc, name="PreconditionFailed", code=412):
                raise

        # Do not silently reuse a conflicting object with the wrong media type/empty content.
        blob.reload()
        if blob.content_type != thumbnail.content_type or not blob.size or int(blob.size) <= 0:
            raise RuntimeError(
                f"Existing thumbnail object conflicts with expected output: gs://{bucket_name}/{object_name}"
            )
        if int(blob.size) > 5 * 1024 * 1024:
            raise RuntimeError(
                f"Existing thumbnail object is unexpectedly large: gs://{bucket_name}/{object_name}"
            )
        generation = getattr(blob, "generation", None)
        if generation is None:
            existing_data = blob.download_as_bytes()
        else:
            existing_data = blob.download_as_bytes(if_generation_match=int(generation))
        try:
            with Image.open(BytesIO(existing_data)) as existing_image:
                if (
                    existing_image.format != "WEBP"
                    or existing_image.size != (thumbnail.width, thumbnail.height)
                ):
                    raise RuntimeError(
                        f"Existing thumbnail dimensions/format conflict: gs://{bucket_name}/{object_name}"
                    )
                existing_image.verify()
        except (UnidentifiedImageError, OSError, ValueError) as verify_error:
            raise RuntimeError(
                f"Existing thumbnail is not a valid WebP image: gs://{bucket_name}/{object_name}"
            ) from verify_error
        logger.info("Reusing existing thumbnail gs://%s/%s", bucket_name, object_name)
        return False
