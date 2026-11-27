"""Consume durable PostgreSQL Outbox rows without a separate broker."""

from contextlib import contextmanager
import json
import logging

import psycopg
from psycopg.rows import dict_row

from event_contract import InvalidEventError, validate_event
from worker_service import PermanentMessageError

logger = logging.getLogger(__name__)
MAX_RETRIES = 8
LEASE_DURATION_SQL = "interval '3 minutes'"


class LeaseLostError(RuntimeError):
    pass


class Outbox:
    def __init__(self, database_url, bucket):
        self.database_url = database_url
        self.bucket = bucket

    def connect(self):
        return psycopg.connect(self.database_url, connect_timeout=5, autocommit=True, row_factory=dict_row,
                               keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=3,
                               )

    @contextmanager
    def claim(self, db):
        with db.transaction():
            row = db.execute(f"""
                SELECT id, status FROM outbox_events
                WHERE event_type = 'PHOTO_UPLOADED' AND (
                  (status = 'PENDING' AND available_at <= now()) OR
                  (status = 'PROCESSING' AND locked_at <= now() - {LEASE_DURATION_SQL})
                )
                ORDER BY available_at, created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED
            """).fetchone()
            event = None
            if row:
                lock_key = str(row["id"])
                locked = db.execute(
                    "SELECT pg_try_advisory_lock(hashtextextended(%s, 317)) AS locked", (lock_key,)
                ).fetchone()["locked"]
                if locked:
                    event = db.execute("""
                        UPDATE outbox_events SET status = 'PROCESSING',
                          attempts = attempts + CASE WHEN status = 'PROCESSING' THEN 1 ELSE 0 END,
                          lease_id = gen_random_uuid(), locked_at = now()
                        WHERE id = %s RETURNING id, lease_id, payload, attempts
                    """, (row["id"],)).fetchone()
        try:
            yield event
        finally:
            if event and not db.closed:
                db.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 317))", (str(event["id"]),))

    @staticmethod
    def renew(db, event):
        changed = db.execute(f"""
            UPDATE outbox_events SET locked_at = now()
            WHERE id = %s AND lease_id = %s AND status = 'PROCESSING'
              AND locked_at > now() - {LEASE_DURATION_SQL}
        """, (event["id"], event["lease_id"])).rowcount
        if not changed:
            raise LeaseLostError("Outbox lease expired")

    @staticmethod
    def finish(db, event, status, *, retry=False):
        changed = db.execute(f"""
            UPDATE outbox_events SET status = %s,
              attempts = attempts + CASE WHEN %s THEN 1 ELSE 0 END,
              available_at = now() + %s * interval '1 second',
              locked_at = NULL, lease_id = NULL,
              last_error = CASE WHEN %s = 'PUBLISHED' THEN NULL ELSE 'Worker delivery failed' END,
              published_at = CASE WHEN %s = 'PUBLISHED' THEN now() ELSE published_at END
            WHERE id = %s AND lease_id = %s AND status = 'PROCESSING'
              AND locked_at > now() - {LEASE_DURATION_SQL}
        """, (status, retry, min(10 * 2 ** min(event["attempts"], 5), 300),
              status, status, event["id"], event["lease_id"])).rowcount
        if not changed:
            raise LeaseLostError("Outbox lease expired")

    def process_one(self, db, make_worker):
        with self.claim(db) as event:
            if not event:
                return False
            photo_id = str(event["id"])
            try:
                payload = validate_event(event["payload"], self.bucket)
                if payload["photoId"] != photo_id:
                    raise InvalidEventError("Outbox ID does not match photo")
            except InvalidEventError:
                # Preserve malformed data for operators instead of repeatedly delivering it.
                self.finish(db, event, "FAILED")
                logger.error("Invalid outbox payload photoId=%s", photo_id)
                return True
            print(json.dumps({"event": "job_attempt", "photoId": photo_id, "jobId": payload["jobId"],
                              "deliveryAttempt": event["attempts"] + 1}), flush=True)
            with make_worker(str(event["lease_id"]), lambda: self.renew(db, event)) as worker:
                try:
                    if event["attempts"] >= MAX_RETRIES:
                        state = worker.status_client.update(photo_id, {
                            "status": "FAILED", "progress": 0, "errorMessage": "Worker retry limit reached"
                        })
                        worker.log_terminal(payload, state, "FAILED")
                        outcome = "PUBLISHED" if state.get("status") == "COMPLETED" else "FAILED"
                    else:
                        worker.process(payload)
                        outcome = "PUBLISHED"
                except PermanentMessageError:
                    # The worker callback durably recorded the image's FAILED state.
                    outcome = "PUBLISHED"
                except Exception as error:
                    logger.warning("Worker delivery failed photoId=%s error=%s", photo_id, type(error).__name__)
                    outcome = "PENDING" if event["attempts"] < MAX_RETRIES else "FAILED"
            self.finish(db, event, outcome, retry=outcome == "PENDING" and event["attempts"] < MAX_RETRIES)
            print(json.dumps({"event": "outbox_delivery", "photoId": photo_id,
                              "jobId": payload["jobId"], "status": outcome}), flush=True)
            return True
