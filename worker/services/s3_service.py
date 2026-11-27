"""Supabase S3 adapter for private originals and deterministic thumbnails."""

import os
from urllib.parse import urlsplit

from botocore.config import Config
from botocore.exceptions import ClientError

from services.gcs_service import OriginalTooLargeError, SourceObjectNotFound


def create_s3_client():
    import boto3

    for name in ("S3_ENDPOINT", "S3_REGION", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_BUCKET"):
        if not os.getenv(name):
            raise RuntimeError(f"Missing {name}")
    endpoint = urlsplit(os.environ["S3_ENDPOINT"])
    local = endpoint.hostname in {"localhost", "127.0.0.1"}
    if ((endpoint.scheme != "https" and not (endpoint.scheme == "http" and local))
            or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment):
        raise RuntimeError("S3_ENDPOINT must be an HTTPS URL or a localhost test URL")
    return boto3.client(
        "s3",
        endpoint_url=os.environ["S3_ENDPOINT"],
        region_name=os.environ["S3_REGION"],
        aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
        config=Config(
            signature_version="s3v4", s3={"addressing_style": "path"},
            request_checksum_calculation="when_required", response_checksum_validation="when_required",
            connect_timeout=5, read_timeout=12, retries={"total_max_attempts": 2, "mode": "standard"},
        ),
    )


class S3ImageStorage:
    def __init__(self, *, max_original_bytes, client=None):
        self.client = client if client is not None else create_s3_client()
        self.max_original_bytes = max_original_bytes

    def download_original(self, bucket_name, object_name):
        try:
            result = self.client.get_object(Bucket=bucket_name, Key=object_name)
        except ClientError as error:
            if error.response["Error"]["Code"] in {"NoSuchKey", "NotFound", "404"}:
                raise SourceObjectNotFound("Original image object was not found") from error
            raise
        body = result["Body"]
        try:
            if result["ContentLength"] <= self.max_original_bytes:
                data = body.read(self.max_original_bytes + 1)
                if len(data) <= self.max_original_bytes:
                    return data
        finally:
            body.close()
        raise OriginalTooLargeError("Original image exceeds the processing size limit")

    def save_thumbnail(self, bucket_name, object_name, thumbnail):
        self.client.put_object(
            Bucket=bucket_name, Key=object_name, Body=thumbnail.data,
            ContentType="image/webp", CacheControl="private, max-age=0, no-transform",
        )
        return True
