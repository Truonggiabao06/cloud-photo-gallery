
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
    '00000000-0000-0000-0000-000000000001',
    'seed-user-001',
    'Cloud Photo Gallery Test Album',
    'Album chứa 100 ảnh hợp lệ và 5 ảnh lỗi',
    'PRIVATE'
)
ON CONFLICT (id) DO NOTHING;


-- 2. Tạo 100 ảnh hợp lệ và 5 ảnh lỗi
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
    '00000000-0000-0000-0000-000000000001',
    'seed-user-001',

    CASE
        WHEN n <= 100
        THEN 'image_' || LPAD(n::TEXT, 3, '0') || '.jpg'
        ELSE 'error_' || LPAD(n::TEXT, 3, '0') || '.jpg'
    END,

    CASE
        WHEN n <= 103 THEN 'image/jpeg'
        ELSE 'application/pdf'
    END,

    1024,

    CASE
        WHEN n <= 100
        THEN 'seed/originals/valid/image_' ||
             LPAD(n::TEXT, 3, '0') || '.jpg'
        ELSE 'seed/originals/invalid/error_' ||
             LPAD(n::TEXT, 3, '0') || '.jpg'
    END,

    'UPLOADED',
    TRUE,

    CASE
        WHEN n <= 100 THEN 'NORMAL'
        WHEN n <= 103 THEN 'CORRUPTED'
        ELSE 'UNSUPPORTED'
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
WHERE is_test_data = TRUE

ON CONFLICT (image_id) DO NOTHING;


-- 4. Tạo sự kiện Outbox
INSERT INTO outbox_events (
    aggregate_type,
    aggregate_id,
    event_type,
    payload,
    status
)
SELECT
    'IMAGE',
    id,
    'IMAGE_UPLOADED',

    jsonb_build_object(
        'imageId', id,
        'originalObjectKey', original_object_key,
        'thumbnailSmallKey', thumbnail_small_key,
        'thumbnailLargeKey', thumbnail_large_key,
        'testCase', test_case
    ),

    'PENDING'

FROM images i
WHERE i.is_test_data = TRUE
AND NOT EXISTS (
    SELECT 1
    FROM outbox_events o
    WHERE o.aggregate_id = i.id
      AND o.event_type = 'IMAGE_UPLOADED'
);

COMMIT;
