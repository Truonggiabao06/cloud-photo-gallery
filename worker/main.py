"""Google Pub/Sub image-processing worker for Cloud Photo Gallery."""
from __future__ import annotations

from concurrent.futures import CancelledError, TimeoutError as FutureTimeoutError
import json
import logging
import signal
import sys
import threading
from typing import Any

from config import load_settings
from event_contract import BucketConfigurationError, InvalidEventError, validate_event
from services.gcs_service import GCSImageStorage
from services.status_api import WorkerStatusClient
from worker_service import PhotoWorker, PermanentMessageError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger("photo-worker")


def _decode_message(data: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidEventError(f"Message data is not valid UTF-8 JSON: {exc}") from exc
    return payload



def handle_message(message, worker: PhotoWorker, expected_bucket: str) -> str:
    """Handle one Pub/Sub message and return the resulting ACK/NACK decision."""
    try:
        payload = _decode_message(message.data)
        event = validate_event(payload, expected_bucket)
    except InvalidEventError as exc:
        logger.error(
            "Dropping malformed message %s (ACK): %s",
            getattr(message, "message_id", "unknown"),
            exc,
        )
        message.ack()
        return "ACK_INVALID"
    except BucketConfigurationError:
        logger.exception("Bucket configuration mismatch; NACK for retry")
        message.nack()
        return "NACK_CONFIGURATION"

    try:
        logger.info(
            "Received PHOTO_UPLOADED photoId=%s messageId=%s",
            event["photoId"],
            getattr(message, "message_id", "unknown"),
        )
        worker.process(event)
        message.ack()
        logger.info("Acknowledged message %s", getattr(message, "message_id", "unknown"))
        return "ACK_PROCESSED"
    except PermanentMessageError as exc:
        logger.error("Permanent processing failure (ACK): %s", exc)
        message.ack()
        return "ACK_PERMANENT"
    except Exception:
        logger.exception("Processing failed; NACK for Pub/Sub retry")
        message.nack()
        return "NACK_RETRY"

def run() -> None:
    # Import cloud SDK only at runtime so pure unit tests need no GCP installation.
    try:
        from google.cloud import pubsub_v1
    except ImportError as exc:
        raise RuntimeError(
            "Google Cloud Pub/Sub SDK is missing. Install worker/requirements.txt first."
        ) from exc

    settings = load_settings()
    subscriber = pubsub_v1.SubscriberClient()
    if settings.pubsub_subscription.startswith("projects/"):
        subscription_path = settings.pubsub_subscription
    else:
        subscription_path = subscriber.subscription_path(
            settings.gcp_project_id, settings.pubsub_subscription
        )

    expected_topic = (
        settings.pubsub_topic
        if settings.pubsub_topic.startswith("projects/")
        else f"projects/{settings.gcp_project_id}/topics/{settings.pubsub_topic}"
    )
    try:
        subscription_info = subscriber.get_subscription(subscription=subscription_path)
    except Exception:
        subscriber.close()
        raise
    if subscription_info.topic != expected_topic:
        subscriber.close()
        raise RuntimeError(
            "Configured Pub/Sub Subscription is attached to a different Topic: "
            f"expected {expected_topic}, got {subscription_info.topic}"
        )

    storage = GCSImageStorage(max_original_bytes=settings.max_original_bytes)
    status_client = WorkerStatusClient(settings)
    worker = PhotoWorker(
        storage=storage,
        status_client=status_client,
        max_image_pixels=settings.max_image_pixels,
    )
    stop_event = threading.Event()

    def callback(message) -> None:
        handle_message(message, worker, settings.gcs_bucket_name)

    flow_control = pubsub_v1.types.FlowControl(max_messages=settings.max_messages)
    streaming_pull = subscriber.subscribe(
        subscription_path,
        callback=callback,
        flow_control=flow_control,
    )
    logger.info("Worker listening on %s", subscription_path)

    def request_shutdown(_signum: int, _frame: Any) -> None:
        logger.info("Shutdown requested")
        stop_event.set()

    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)

    try:
        while not stop_event.wait(1):
            if streaming_pull.done():
                # Propagate an unexpected subscriber failure to the process supervisor.
                streaming_pull.result()
                break
    finally:
        streaming_pull.cancel()
        try:
            # Allow the Pub/Sub client to stop the streaming pull and finish callbacks.
            streaming_pull.result(timeout=settings.shutdown_grace_seconds)
        except CancelledError:
            pass
        except FutureTimeoutError:
            logger.warning(
                "Subscriber did not stop within %s seconds; process will exit",
                settings.shutdown_grace_seconds,
            )
        except Exception:
            logger.debug("Subscriber closed with a terminal exception", exc_info=True)
        subscriber.close()
        logger.info("Worker stopped")


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        logger.exception("Worker startup/runtime failure: %s", exc)
        sys.exit(1)
