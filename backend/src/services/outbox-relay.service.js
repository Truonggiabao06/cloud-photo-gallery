const { query } = require("../config/database");
const { publishPhotoUploaded } = require("./queue.service");

async function dispatchNext(publish = publishPhotoUploaded) {
  const { rows: [event] } = await query(`
    WITH candidate AS (
      SELECT id FROM outbox_events
      WHERE event_type = 'PHOTO_UPLOADED' AND (
        (status = 'PENDING' AND available_at <= now()) OR
        (status = 'PROCESSING' AND locked_at <= now() - INTERVAL '3 minutes')
      )
      ORDER BY available_at, created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED
    )
    UPDATE outbox_events e SET status = 'PROCESSING', locked_at = now(), lease_id = gen_random_uuid()
    FROM candidate WHERE e.id = candidate.id RETURNING e.id, e.lease_id, e.payload, e.attempts
  `);
  if (!event) return null;

  let messageId;
  try {
    messageId = await publish(event.payload);
  } catch (error) {
    const failures = event.attempts + 1;
    const delay = Math.min(2 ** failures * 5, 300);
    const status = failures >= 8 ? "FAILED" : "PENDING";
    const { rowCount } = await query(`
      UPDATE outbox_events SET status = $3, attempts = $4,
        available_at = now() + $5 * INTERVAL '1 second', locked_at = NULL, lease_id = NULL, last_error = $6
      WHERE id = $1 AND lease_id = $2 AND status = 'PROCESSING'
    `, [event.id, event.lease_id, status, failures, delay, error.name || "PublishError"]);
    if (!rowCount) return "LEASE_LOST";
    console.error(JSON.stringify({ event: "outbox_publish_failed", photoId: event.payload.photoId, failures, status }));
    return status;
  }
  const { rowCount } = await query(`
    UPDATE outbox_events SET status = 'PUBLISHED', published_at = now(), pubsub_message_id = $3,
      locked_at = NULL, lease_id = NULL, last_error = NULL
    WHERE id = $1 AND lease_id = $2 AND status = 'PROCESSING'
  `, [event.id, event.lease_id, messageId]);
  return rowCount ? "PUBLISHED" : "LEASE_LOST";
}

module.exports = { dispatchNext };
