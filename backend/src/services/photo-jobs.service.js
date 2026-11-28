const { transaction } = require("../config/database");
const { photoUploadedPayload } = require("./queue.service");

async function createPhotoJob(details) {
  return transaction(async db => {
    const { rows: [photo] } = await db.query(`
      INSERT INTO images (id, album_id, owner_id, original_object_key, original_filename,
                          mime_type, file_size, checksum_sha256, status)
      VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'PENDING')
      RETURNING id AS "_id", album_id AS "albumId", owner_id AS "ownerId",
                original_object_key AS "originalObject", mime_type AS "mimeType",
                created_at AS "createdAt", status, progress
    `, [details._id, details.albumId, details.ownerId, details.originalObject,
      details.originalName, details.mimeType, details.size, details.checksumSha256]);
    const { rows: [{ id: jobId }] } = await db.query(
      "INSERT INTO processing_jobs (image_id) VALUES ($1) RETURNING id", [photo._id]);
    const payload = photoUploadedPayload({ ...photo, jobId, requestId: details.requestId });
    await db.query(`
      INSERT INTO outbox_events (id, aggregate_type, aggregate_id, event_type, payload)
      VALUES ($1, 'IMAGE', $1, 'PHOTO_UPLOADED', $2)
    `, [photo._id, payload]);
    return { ...photo, jobId };
  });
}

async function updatePhotoJob(id, update, leaseId) {
  return transaction(async db => {
    if (leaseId) {
      const { rowCount } = await db.query(`
        UPDATE outbox_events SET locked_at = now()
        WHERE id = $1 AND lease_id = $2 AND status = 'PROCESSING'
          AND locked_at > now() - interval '3 minutes'
      `, [id, leaseId]);
      if (!rowCount) return { leaseLost: true };
    }
    const { rows: [existing] } = await db.query(`
      SELECT i.id AS "_id", i.status, i.progress, j.id AS "jobId"
      FROM images i LEFT JOIN processing_jobs j ON j.image_id = i.id
      WHERE i.id = $1 FOR UPDATE OF i
    `, [id]);
    if (!existing) return { photo: null };
    if (["COMPLETED", "FAILED"].includes(existing.status)) {
      return { photo: existing, alreadyTerminal: true, terminalCommit: false };
    }

    const terminal = ["COMPLETED", "FAILED"].includes(update.status);
    const progress = terminal ? (update.status === "COMPLETED" ? 100 : 0)
      : Math.max(existing.progress, update.progress ?? 0);
    const status = existing.status === "PROCESSING" && update.status === "PENDING"
      ? existing.status : update.status;
    const jobStatus = status === "PENDING" ? "QUEUED" : status;
    await db.query(`UPDATE images SET status = $2, progress = $3,
      error_message = $4, processed_at = CASE WHEN $5 THEN now() ELSE NULL END WHERE id = $1`,
    [id, status, progress, update.errorMessage ?? null, terminal]);
    const { rows: [{ id: jobId }] } = await db.query(`
      INSERT INTO processing_jobs (image_id, status, started_at, completed_at, last_error)
      VALUES ($1, $2::varchar, CASE WHEN $2::varchar <> 'QUEUED' THEN now() END,
                       CASE WHEN $3 THEN now() END, $4)
      ON CONFLICT (image_id) DO UPDATE SET status = EXCLUDED.status,
        started_at = COALESCE(processing_jobs.started_at, EXCLUDED.started_at),
        completed_at = EXCLUDED.completed_at, last_error = EXCLUDED.last_error
      RETURNING id
    `, [id, jobStatus, terminal, update.errorMessage ?? null]);
    if (terminal) {
      await db.query(`INSERT INTO processed_events (event_id, idempotency_key, image_id, event_type, payload)
        VALUES ($1::text, 'PHOTO_UPLOADED:' || $1::text, $1::uuid, 'PHOTO_UPLOADED', $2)`,
      [id, { photoId: id, jobId, status, thumbnailBytes: update.thumbnailBytes }]);
    }
    return { photo: { _id: id, jobId, status, progress }, alreadyTerminal: false, terminalCommit: terminal };
  });
}

module.exports = { createPhotoJob, updatePhotoJob };
