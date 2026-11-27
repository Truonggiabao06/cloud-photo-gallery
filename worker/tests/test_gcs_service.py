import unittest
from io import BytesIO

from PIL import Image

from processors.image_processor import Thumbnail
from services.gcs_service import (
    GCSImageStorage,
    OriginalTooLargeError,
    SourceObjectNotFound,
)


class NotFound(Exception):
    code = 404


class PreconditionFailed(Exception):
    code = 412


def make_webp(size=(10, 10)):
    stream = BytesIO()
    Image.new("RGB", size, (10, 30, 50)).save(stream, format="WEBP")
    return stream.getvalue()


class FakeBlob:
    def __init__(self, *, data=None, size=None, content_type="image/webp", upload_error=None):
        data = data if data is not None else make_webp()
        self.data = data
        self.size = len(data) if size is None else size
        self.content_type = content_type
        self.generation = 7
        self.upload_error = upload_error
        self.upload_kwargs = None
        self.reload_error = None

    def reload(self):
        if self.reload_error:
            raise self.reload_error

    def download_as_bytes(self, **kwargs):
        self.download_kwargs = kwargs
        return self.data

    def upload_from_string(self, data, **kwargs):
        self.upload_kwargs = kwargs
        if self.upload_error:
            raise self.upload_error
        self.data = data
        self.size = len(data)


class FakeBucket:
    def __init__(self, blob):
        self._blob = blob

    def blob(self, name):
        return self._blob


class FakeClient:
    def __init__(self, blob):
        self._bucket = FakeBucket(blob)

    def bucket(self, name):
        return self._bucket


class GCSServiceTests(unittest.TestCase):
    def test_download_pins_generation(self):
        blob = FakeBlob(data=b"image-data")
        storage = GCSImageStorage(max_original_bytes=100, client=FakeClient(blob))
        self.assertEqual(storage.download_original("bucket", "original/a.jpg"), b"image-data")
        self.assertEqual(blob.download_kwargs["if_generation_match"], 7)

    def test_download_rejects_oversized_object_before_read(self):
        blob = FakeBlob(size=101)
        storage = GCSImageStorage(max_original_bytes=100, client=FakeClient(blob))
        with self.assertRaises(OriginalTooLargeError):
            storage.download_original("bucket", "original/a.jpg")
        self.assertFalse(hasattr(blob, "download_kwargs"))

    def test_download_maps_gcs_not_found(self):
        blob = FakeBlob()
        blob.reload_error = NotFound("missing")
        storage = GCSImageStorage(max_original_bytes=100, client=FakeClient(blob))
        with self.assertRaises(SourceObjectNotFound):
            storage.download_original("bucket", "original/a.jpg")

    def test_save_uses_create_only_precondition(self):
        blob = FakeBlob()
        storage = GCSImageStorage(max_original_bytes=100, client=FakeClient(blob))
        thumb = Thumbnail("small", 10, 10, make_webp())
        self.assertTrue(storage.save_thumbnail("bucket", "thumb.webp", thumb))
        self.assertEqual(blob.upload_kwargs["if_generation_match"], 0)
        self.assertEqual(blob.upload_kwargs["content_type"], "image/webp")

    def test_save_reuses_existing_valid_object_on_412(self):
        blob = FakeBlob(upload_error=PreconditionFailed("already exists"))
        storage = GCSImageStorage(max_original_bytes=100, client=FakeClient(blob))
        thumb = Thumbnail("small", 10, 10, make_webp())
        self.assertFalse(storage.save_thumbnail("bucket", "thumb.webp", thumb))

    def test_save_rejects_existing_corrupt_object(self):
        blob = FakeBlob(data=b"not-webp", content_type="image/webp", upload_error=PreconditionFailed("exists"))
        storage = GCSImageStorage(max_original_bytes=100, client=FakeClient(blob))
        thumb = Thumbnail("small", 10, 10, make_webp())
        with self.assertRaisesRegex(RuntimeError, "not a valid WebP"):
            storage.save_thumbnail("bucket", "thumb.webp", thumb)


if __name__ == "__main__":
    unittest.main()
