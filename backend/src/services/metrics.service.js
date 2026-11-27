const { query } = require("../config/database");

async function readMetrics() {
  const { rows: [metrics] } = await query(`
    WITH terminal AS (
      SELECT status, EXTRACT(EPOCH FROM (processed_at - created_at)) AS seconds
      FROM images
      WHERE status IN ('COMPLETED', 'FAILED') AND processed_at >= now() - interval '1 hour'
    )
    SELECT now() AS "sampledAt",
      (SELECT COALESCE(EXTRACT(EPOCH FROM (now() - min(created_at))), 0)::float8
       FROM images WHERE status IN ('UPLOADED', 'PENDING', 'PROCESSING')) AS "oldestPendingJobAgeSeconds",
      (SELECT count(*)::int FROM images WHERE status IN ('UPLOADED', 'PENDING', 'PROCESSING')) AS "pendingJobs",
      (SELECT avg(seconds)::float8 FROM terminal WHERE status = 'COMPLETED') AS "averageLatencySeconds",
      (SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY seconds) FROM terminal
       WHERE status = 'COMPLETED') AS "p95LatencySeconds",
      (SELECT count(*)::int FROM terminal) AS "terminalJobs",
      (SELECT count(*) FILTER (WHERE status = 'FAILED')::float8 / NULLIF(count(*), 0) FROM terminal) AS "failureRate",
      (SELECT COALESCE(sum(attempts), 0)::float8 FROM outbox_events
       WHERE event_type = 'PHOTO_UPLOADED') AS "totalRetries",
      (SELECT COALESCE(sum((e.payload->>'thumbnailBytes')::bigint), 0)::float8
       FROM processed_events e JOIN images i ON i.id = e.image_id
       WHERE i.status = 'COMPLETED' AND e.event_type = 'PHOTO_UPLOADED'
         AND e.payload->>'thumbnailBytes' ~ '^[0-9]{1,8}$') AS "thumbnailBytes",
      (SELECT count(*)::int FROM images i
       WHERE i.status = 'COMPLETED' AND NOT EXISTS (
         SELECT 1 FROM processed_events e WHERE e.image_id = i.id
           AND e.event_type = 'PHOTO_UPLOADED'
           AND e.payload->>'thumbnailBytes' ~ '^[0-9]{1,8}$'
       )) AS "completedWithoutThumbnailSize"
  `);
  return { windowSeconds: 3600, ...metrics };
}

module.exports = { readMetrics };
