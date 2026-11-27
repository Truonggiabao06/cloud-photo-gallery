import json
import unittest

from main import handle_message
from worker_service import PermanentMessageError

PHOTO_ID = "01234567-89ab-cdef-0123-456701234567"
ALBUM_ID = "abcdef01-2345-6789-abcd-ef0101234567"
BUCKET = "gallery-private-bucket"


def event():
    return {
        "eventType": "PHOTO_UPLOADED",
        "eventVersion": 1,
        "photoId": PHOTO_ID,
        "albumId": ALBUM_ID,
        "userId": "user-123",
        "bucket": BUCKET,
        "originalObject": f"original/user-123/{ALBUM_ID}/photo.jpg",
        "mimeType": "image/jpeg",
        "createdAt": "2026-11-27T01:00:00Z",
    }


class FakeMessage:
    message_id = "message-1"

    def __init__(self, data):
        self.data = data
        self.acked = 0
        self.nacked = 0

    def ack(self):
        self.acked += 1

    def nack(self):
        self.nacked += 1


class FakeWorker:
    def __init__(self, error=None):
        self.error = error
        self.events = []

    def process(self, event_data):
        self.events.append(event_data)
        if self.error:
            raise self.error
        return {"small": "s", "large": "l"}


class MessageHandlingTests(unittest.TestCase):
    def test_success_is_acked(self):
        message = FakeMessage(json.dumps(event()).encode())
        worker = FakeWorker()
        result = handle_message(message, worker, BUCKET)
        self.assertEqual(result, "ACK_PROCESSED")
        self.assertEqual((message.acked, message.nacked), (1, 0))

    def test_invalid_json_is_acked(self):
        message = FakeMessage(b"not-json")
        result = handle_message(message, FakeWorker(), BUCKET)
        self.assertEqual(result, "ACK_INVALID")
        self.assertEqual((message.acked, message.nacked), (1, 0))

    def test_bucket_config_mismatch_is_nacked(self):
        message = FakeMessage(json.dumps(event()).encode())
        result = handle_message(message, FakeWorker(), "another-bucket")
        self.assertEqual(result, "NACK_CONFIGURATION")
        self.assertEqual((message.acked, message.nacked), (0, 1))

    def test_permanent_processing_failure_is_acked(self):
        message = FakeMessage(json.dumps(event()).encode())
        result = handle_message(message, FakeWorker(PermanentMessageError("bad image")), BUCKET)
        self.assertEqual(result, "ACK_PERMANENT")
        self.assertEqual((message.acked, message.nacked), (1, 0))

    def test_transient_processing_failure_is_nacked(self):
        message = FakeMessage(json.dumps(event()).encode())
        result = handle_message(message, FakeWorker(RuntimeError("network down")), BUCKET)
        self.assertEqual(result, "NACK_RETRY")
        self.assertEqual((message.acked, message.nacked), (0, 1))


if __name__ == "__main__":
    unittest.main()
