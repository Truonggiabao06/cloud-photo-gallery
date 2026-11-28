
-- Run only on a dedicated test database. Set photo.seed_bucket for this session
-- only after loading fixture objects at the keys below. Without it, seed metadata
-- and album membership without enqueuing jobs against missing storage objects.
BEGIN;

-- 1. Tạo album dữ liệu kiểm thử
INSERT INTO albums (
    id,
    owner_id,
    name,
    description,
    visibility
)
VALUES (
    '00000000-0000-0000-0000-000000000107',
    'seed-user-001',
    'Cloud Photo Gallery Test Album',
    'Album chứa 100 ảnh hợp lệ và 5 ảnh lỗi',
    'SHARED'
)
ON CONFLICT (id) DO NOTHING;


INSERT INTO album_members (album_id, member_id, member_role, invited_by)
VALUES ('00000000-0000-0000-0000-000000000107', 'seed-viewer-001', 'VIEWER', 'seed-user-001')
ON CONFLICT (album_id, member_id) DO NOTHING;

-- 2. Tạo metadata cho 100 ảnh hợp lệ và 5 ảnh lỗi
INSERT INTO images (
    album_id,
    owner_id,
    original_filename,
    mime_type,
    file_size,
    original_object_key,
    status,
    is_test_data,
    test_case
)
SELECT
    '00000000-0000-0000-0000-000000000107',
    'seed-user-001',

    CASE
        WHEN n <= 100
        THEN 'image_' || LPAD(n::TEXT, 3, '0') || CASE WHEN n % 2 = 0 THEN '.png' ELSE '.jpg' END
        ELSE 'error_' || LPAD(n::TEXT, 3, '0') || '.jpg'
    END,

    CASE
        WHEN n <= 100 AND n % 2 = 0 THEN 'image/png'
        ELSE 'image/jpeg'
    END,

    1024,

    'original/seed-user-001/00000000-0000-0000-0000-000000000107/' ||
    CASE
        WHEN n <= 100 THEN 'image_' || LPAD(n::TEXT, 3, '0') ||
             CASE WHEN n % 2 = 0 THEN '.png' ELSE '.jpg' END
        ELSE 'error_' || LPAD(n::TEXT, 3, '0') || '.jpg'
    END,

    'UPLOADED',
    TRUE,

    CASE
        WHEN n <= 100 THEN 'NORMAL'
        ELSE 'CORRUPTED'
    END

FROM generate_series(1, 105) AS n

ON CONFLICT (original_object_key) DO NOTHING;


-- 3. Tạo công việc xử lý ảnh
INSERT INTO processing_jobs (
    image_id,
    status
)
SELECT
    id,
    'QUEUED'
FROM images
WHERE is_test_data AND album_id = '00000000-0000-0000-0000-000000000107'

ON CONFLICT (image_id) DO NOTHING;


-- 4. Tạo sự kiện Outbox
INSERT INTO outbox_events (id, aggregate_type, aggregate_id, event_type, payload)
SELECT i.id, 'IMAGE', i.id, 'PHOTO_UPLOADED',
    jsonb_build_object(
        'eventType', 'PHOTO_UPLOADED',
        'eventVersion', 1,
        'photoId', i.id,
        'jobId', j.id,
        'albumId', i.album_id,
        'userId', i.owner_id,
        'bucket', current_setting('photo.seed_bucket', true),
        'originalObject', i.original_object_key,
        'mimeType', i.mime_type,
        'createdAt', i.created_at
    )
FROM images i
JOIN processing_jobs j ON j.image_id = i.id
WHERE i.is_test_data AND i.album_id = '00000000-0000-0000-0000-000000000107'
AND nullif(current_setting('photo.seed_bucket', true), '') IS NOT NULL
ON CONFLICT (id) DO NOTHING;

COMMIT;
