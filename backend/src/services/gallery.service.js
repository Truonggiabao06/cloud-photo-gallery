const { query } = require("../config/database");

const uuidPattern = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
const isUuid = value => typeof value === "string" && uuidPattern.test(value);
const albumFields = `a.id AS "_id", a.owner_id AS "ownerId", a.name, a.description,
  a.visibility, a.created_at AS "createdAt", a.updated_at AS "updatedAt"`;
const canReadAlbum = `(a.owner_id = $1 OR EXISTS (
  SELECT 1 FROM album_members m WHERE m.album_id = a.id AND m.member_id = $1
))`;
const photoFields = `i.id AS "_id", j.id AS "jobId", i.album_id AS "albumId", i.owner_id AS "ownerId",
  i.original_object_key AS "originalObject", i.original_filename AS "originalName",
  i.mime_type AS "mimeType", i.file_size::int AS size,
  CASE WHEN i.status = 'UPLOADED' THEN 'PENDING' ELSE i.status END AS status,
  i.progress, i.error_message AS "errorMessage",
  i.created_at AS "createdAt", i.updated_at AS "updatedAt",
  CASE WHEN i.status = 'COMPLETED' THEN i.thumbnail_small_key END AS "thumbnailSmallObject",
  CASE WHEN i.status = 'COMPLETED' THEN i.thumbnail_large_key END AS "thumbnailLargeObject",
  CASE WHEN i.status = 'COMPLETED' THEN i.thumbnail_large_key END AS "thumbnailObject"`;

async function createAlbum(name, description, ownerId) {
  const { rows } = await query(`
    INSERT INTO albums AS a (name, description, owner_id) VALUES ($1, $2, $3)
    RETURNING ${albumFields}`, [name, description, ownerId]);
  return rows[0];
}

async function listAlbums(userId) {
  const { rows } = await query(`SELECT ${albumFields} FROM albums a
    WHERE ${canReadAlbum} ORDER BY a.created_at DESC`, [userId]);
  return rows;
}

async function findAlbum(userId, id) {
  if (!isUuid(id)) return undefined;
  const { rows } = await query(`SELECT ${albumFields},
    (SELECT count(*)::int FROM images WHERE album_id = a.id) AS "photoCount"
    FROM albums a WHERE ${canReadAlbum} AND a.id = $2`, [userId, id]);
  return rows[0];
}

async function findOwnedAlbum(userId, id) {
  if (!isUuid(id)) return undefined;
  const { rows } = await query("SELECT id FROM albums WHERE owner_id = $1 AND id = $2", [userId, id]);
  return rows[0];
}

async function inviteViewer(ownerId, id, viewerId) {
  if (!isUuid(id)) return undefined;
  const { rows } = await query(`
    WITH owned AS (
      UPDATE albums SET visibility = 'SHARED' WHERE owner_id = $1 AND id = $2 RETURNING id
    )
    INSERT INTO album_members (album_id, member_id, member_role, invited_by)
    SELECT id, $3, 'VIEWER', $1 FROM owned
    ON CONFLICT (album_id, member_id) DO UPDATE SET invited_by = EXCLUDED.invited_by
    RETURNING album_id AS "albumId", member_id AS "memberId", member_role AS "role"
  `, [ownerId, id, viewerId]);
  return rows[0];
}

async function listPhotos(userId, albumId) {
  if (albumId !== undefined && !isUuid(albumId)) return [];
  const { rows } = await query(`SELECT ${photoFields} FROM images i
    JOIN albums a ON a.id = i.album_id LEFT JOIN processing_jobs j ON j.image_id = i.id
    WHERE ${canReadAlbum}
      AND ($2::uuid IS NULL OR a.id = $2) ORDER BY i.created_at DESC, i.id DESC LIMIT 200`,
  [userId, albumId ?? null]);
  return rows;
}

async function findPhoto(userId, id) {
  if (!isUuid(id)) return undefined;
  const { rows } = await query(`SELECT ${photoFields} FROM images i
    JOIN albums a ON a.id = i.album_id LEFT JOIN processing_jobs j ON j.image_id = i.id
    WHERE ${canReadAlbum} AND i.id = $2`, [userId, id]);
  return rows[0];
}

module.exports = { isUuid, createAlbum, listAlbums, findAlbum, findOwnedAlbum, inviteViewer, listPhotos, findPhoto };
