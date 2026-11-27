import unittest

from event_contract import BucketConfigurationError, InvalidEventError, validate_event


PHOTO_ID = "0123456789abcdef01234567"
ALBUM_ID = "abcdef0123456789abcdef01"
BUCKET = "gallery-private-bucket"


def valid_event():
    return {
        "eventType": "PHOTO_UPLOADED",
        "eventVersion": 1,
        "photoId": PHOTO_ID,
        "albumId": ALBUM_ID,
        "userId": "entra-subject-123",
        "bucket": BUCKET,
        "originalObject": f"original/entra-subject-123/{ALBUM_ID}/example.jpg",
        "mimeType": "image/jpeg",
        "createdAt": "2026-11-27T01:00:00.000Z",
    }


class EventContractTests(unittest.TestCase):
    def test_accepts_member2_event_shape(self):
        result = validate_event(valid_event(), BUCKET)
        self.assertEqual(result["photoId"], PHOTO_ID)
        self.assertEqual(result["eventType"], "PHOTO_UPLOADED")

    def test_rejects_missing_contract_field(self):
        event = valid_event()
        del event["userId"]
        with self.assertRaises(InvalidEventError):
            validate_event(event, BUCKET)

    def test_rejects_boolean_event_version(self):
        event = valid_event()
        event["eventVersion"] = True
        with self.assertRaises(InvalidEventError):
            validate_event(event, BUCKET)

    def test_bucket_mismatch_is_a_configuration_error(self):
        with self.assertRaises(BucketConfigurationError):
            validate_event(valid_event(), "different-bucket")

    def test_rejects_object_key_for_another_user_or_album(self):
        event = valid_event()
        event["originalObject"] = f"original/other-user/{ALBUM_ID}/example.jpg"
        with self.assertRaises(InvalidEventError):
            validate_event(event, BUCKET)

    def test_rejects_path_traversal(self):
        event = valid_event()
        event["originalObject"] = f"original/entra-subject-123/{ALBUM_ID}/../secret.jpg"
        with self.assertRaises(InvalidEventError):
            validate_event(event, BUCKET)

    def test_rejects_bad_mongo_ids(self):
        event = valid_event()
        event["photoId"] = "not-an-object-id"
        with self.assertRaises(InvalidEventError):
            validate_event(event, BUCKET)

    def test_rejects_timestamp_without_timezone(self):
        event = valid_event()
        event["createdAt"] = "2026-11-27T01:00:00"
        with self.assertRaises(InvalidEventError):
            validate_event(event, BUCKET)

    def test_unsupported_mime_is_left_for_worker_to_mark_failed(self):
        event = valid_event()
        event["mimeType"] = "application/octet-stream"
        result = validate_event(event, BUCKET)
        self.assertEqual(result["mimeType"], "application/octet-stream")

    def test_rejects_non_string_mime_without_crashing(self):
        event = valid_event()
        event["mimeType"] = ["image/jpeg"]
        with self.assertRaises(InvalidEventError):
            validate_event(event, BUCKET)


if __name__ == "__main__":
    unittest.main()
