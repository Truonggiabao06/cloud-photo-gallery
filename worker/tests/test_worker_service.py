from io import BytesIO
import unittest

from PIL import Image

from services.gcs_service import OriginalTooLargeError, SourceObjectNotFound
from worker_service import PermanentMessageError, PhotoWorker


PHOTO_ID = "01234567-89ab-cdef-0123-456701234567"


def jpeg_bytes():
    stream = BytesIO()
    Image.new("RGB", (1000, 700), (30, 80, 120)).save(stream, format="JPEG")
    return stream.getvalue()


def event():
    return {
        "photoId": PHOTO_ID,
        "bucket": "gallery-private-bucket",
        "originalObject": "original/user/album/photo.jpg",
        "mimeType": "image/jpeg",
    }


class FakeStorage:
    def __init__(self, data=None, error=None):
        self.data = data if data is not None else jpeg_bytes()
        self.error = error
        self.saved = {}
        self.save_calls = []

    def download_original(self, bucket, object_name):
        if self.error:
            raise self.error
        return self.data

    def save_thumbnail(self, bucket, object_name, thumbnail):
        self.save_calls.append((bucket, object_name, thumbnail))
        self.saved.setdefault(object_name, thumbnail.data)
        return len(self.save_calls) <= 2


class FakeStatusClient:
    def __init__(self):
        self.updates = []
        self.error_on_status = None

    def update(self, photo_id, payload):
        if payload.get("status") == self.error_on_status:
            raise RuntimeError("simulated Backend API failure")
        self.updates.append((photo_id, dict(payload)))


class WorkerServiceTests(unittest.TestCase):
    def test_success_creates_two_outputs_and_updates_backend_contract(self):
        storage = FakeStorage()
        status = FakeStatusClient()
        worker = PhotoWorker(storage, status)

        outputs = worker.process(event())

        self.assertEqual(outputs["small"], f"thumbnails/{PHOTO_ID}/small.webp")
        self.assertEqual(outputs["large"], f"thumbnails/{PHOTO_ID}/large.webp")
        self.assertEqual(len(storage.save_calls), 2)
        self.assertEqual(status.updates[-1][1], {
            "status": "COMPLETED",
            "progress": 100,
            "thumbnailObject": f"thumbnails/{PHOTO_ID}/large.webp",
            "thumbnailSmallObject": f"thumbnails/{PHOTO_ID}/small.webp",
            "thumbnailLargeObject": f"thumbnails/{PHOTO_ID}/large.webp",
        })

    def test_redelivery_uses_same_deterministic_keys(self):
        storage = FakeStorage()
        status = FakeStatusClient()
        worker = PhotoWorker(storage, status)
        first = worker.process(event())
        second = worker.process(event())
        self.assertEqual(first, second)
        self.assertEqual(set(storage.saved), {first["small"], first["large"]})

    def test_corrupt_image_is_marked_failed_and_permanent(self):
        status = FakeStatusClient()
        worker = PhotoWorker(FakeStorage(data=b"bad image"), status)
        with self.assertRaises(PermanentMessageError):
            worker.process(event())
        self.assertEqual(status.updates[-1][1]["status"], "FAILED")

    def test_source_not_found_is_marked_failed(self):
        status = FakeStatusClient()
        worker = PhotoWorker(FakeStorage(error=SourceObjectNotFound("missing")), status)
        with self.assertRaises(PermanentMessageError):
            worker.process(event())
        self.assertEqual(status.updates[-1][1]["status"], "FAILED")

    def test_oversized_source_is_marked_failed(self):
        status = FakeStatusClient()
        worker = PhotoWorker(FakeStorage(error=OriginalTooLargeError("too big")), status)
        with self.assertRaises(PermanentMessageError):
            worker.process(event())
        self.assertEqual(status.updates[-1][1]["status"], "FAILED")

    def test_backend_failure_is_not_swallowed(self):
        status = FakeStatusClient()
        status.error_on_status = "COMPLETED"
        worker = PhotoWorker(FakeStorage(), status)
        with self.assertRaisesRegex(RuntimeError, "simulated Backend API failure"):
            worker.process(event())

    def test_invalid_photo_id_is_permanent(self):
        worker = PhotoWorker(FakeStorage(), FakeStatusClient())
        invalid = event()
        invalid["photoId"] = "bad-id"
        with self.assertRaises(PermanentMessageError):
            worker.process(invalid)

    def test_unsupported_mime_is_marked_failed(self):
        status = FakeStatusClient()
        unsupported = event()
        unsupported["mimeType"] = "application/octet-stream"
        worker = PhotoWorker(FakeStorage(), status)
        with self.assertRaises(PermanentMessageError):
            worker.process(unsupported)
        self.assertEqual(status.updates[-1][1]["status"], "FAILED")


if __name__ == "__main__":
    unittest.main()
