require("dotenv").config();

const assert = require("node:assert/strict");
const { randomUUID, createHash } = require("node:crypto");
const { setTimeout: wait } = require("node:timers/promises");
const { ListObjectsV2Command } = require("@aws-sdk/client-s3");
const { connectDatabase, closeDatabase, query } = require("../src/config/database");
const { createS3Storage } = require("../src/config/s3");
const { uploadImage, createSignedReadUrl } = require("../src/services/storage.service");
const { createAlbum } = require("../src/services/gallery.service");
const { createPhotoJob } = require("../src/services/photo-jobs.service");
const { workerOrigin } = require("../src/services/worker-wake.service");

const fixturePng = "iVBORw0KGgoAAAANSUhEUgAAABgAAAAQCAIAAACDRijCAAAAHElEQVR4nGP8IGfEQA3ARBVTRg0aNWjUoBFsEAAAKAFgnxe+9QAAAABJRU5ErkJggg==";
const sha256 = bytes => createHash("sha256").update(bytes).digest("hex");

async function wakeWorker() {
  const response = await fetch(`${workerOrigin()}/wake`, {
    method: "POST", headers: { "x-worker-secret": process.env.WORKER_SHARED_SECRET },
    signal: AbortSignal.timeout(90000), redirect: "error"
  });
  assert.equal(response.status, 202);
}

async function fetchObject(key, verifyPrivate = false) {
  const signed = new URL(await createSignedReadUrl(key));
  if (verifyPrivate) {
    const unsigned = new URL(signed);
    unsigned.search = "";
    const response = await fetch(unsigned, { signal: AbortSignal.timeout(15000), redirect: "error" });
    try {
      assert.ok([401, 403, 404].includes(response.status), "Unsigned original must be inaccessible");
    } finally {
      await response.body?.cancel();
    }
  }
  const response = await fetch(signed, { signal: AbortSignal.timeout(15000), redirect: "error" });
  assert.equal(response.status, 200);
  return Buffer.from(await response.arrayBuffer());
}

async function waitForDelivery(photoId, expectedAttempts) {
  for (let i = 0; i < 90; i++) {
    const { rows: [row] } = await query(`
      SELECT e.status AS delivery, i.status AS image_status, e.attempts
      FROM outbox_events e JOIN images i ON i.id = e.aggregate_id WHERE e.id = $1
    `, [photoId]);
    assert.ok(row && row.delivery !== "FAILED" && row.image_status !== "FAILED", "Worker failed the test job");
    if (row.delivery === "PUBLISHED" && row.image_status === "COMPLETED" && row.attempts >= expectedAttempts) {
      return;
    }
    await wait(2000);
  }
  throw new Error("Worker did not complete the test delivery");
}

async function run() {
  assert.equal(process.env.STORAGE_BACKEND, "s3");
  assert.equal(process.env.QA_CONFIRM_STAGING, "yes", "Run this on a dedicated staging project");
  const { client, bucket } = createS3Storage();
  try {
    await connectDatabase();
    const photoId = randomUUID();
    const bytes = Buffer.from(fixturePng, "base64");
    const ownerId = `qa-s3-${photoId}`;
    const album = await createAlbum("Supabase S3 smoke test", "", ownerId);
    const originalObject = `original/${ownerId}/${album._id}/${photoId}.png`;
    await uploadImage(bytes, originalObject, "image/png");
    console.log(JSON.stringify({ photoId, albumId: album._id, event: "staging_fixture_created" }));
    assert.deepEqual(await fetchObject(originalObject, true), bytes);
    await createPhotoJob({
      _id: photoId, albumId: album._id, ownerId, originalObject, originalName: "fixture.png",
      mimeType: "image/png", size: bytes.length, checksumSha256: sha256(bytes)
    });
    await wakeWorker();
    await waitForDelivery(photoId, 0);

    const prefix = `thumbnails/${photoId}/`;
    const keys = [`${prefix}large.webp`, `${prefix}small.webp`];
    const before = await Promise.all(keys.map(async key => {
      const object = await fetchObject(key, true);
      assert.equal(object.subarray(8, 12).toString(), "WEBP");
      return object;
    }));
    // Requeue only the synthetic event this invocation created.
    const { rowCount } = await query(`
      UPDATE outbox_events SET status = 'PENDING', available_at = now(), attempts = attempts + 1
      WHERE id = $1 AND status = 'PUBLISHED'
    `, [photoId]);
    assert.equal(rowCount, 1);
    await wakeWorker();
    await waitForDelivery(photoId, 1);

    const after = await Promise.all(keys.map(key => fetchObject(key)));
    assert.deepEqual(after.map(sha256), before.map(sha256));
    const listed = await client.send(new ListObjectsV2Command({ Bucket: bucket, Prefix: prefix }),
      { abortSignal: AbortSignal.timeout(15000) });
    assert.deepEqual((listed.Contents || []).map(item => item.Key).sort(), keys);
    const { rows: [counts] } = await query(`
      SELECT (SELECT count(*)::int FROM processing_jobs WHERE image_id = $1 AND status = 'COMPLETED') AS jobs,
             (SELECT count(*)::int FROM processed_events WHERE image_id = $1) AS events
    `, [photoId]);
    assert.deepEqual(counts, { jobs: 1, events: 1 });
    console.log(JSON.stringify({ photoId, privatePresign: "passed", replay: "passed", thumbnails: keys.length }));
  } finally {
    client.destroy();
    await closeDatabase();
  }
}

run().catch(error => {
  // Error details may contain signed URLs or storage endpoint metadata.
  console.error("Supabase verification failed", error.name, error.code || "");
  process.exitCode = 1;
});
