
SELECT
    test_case,
    COUNT(*) AS total_images
FROM images
WHERE is_test_data = TRUE
GROUP BY test_case
ORDER BY test_case;

SELECT
    status,
    COUNT(*) AS total_jobs
FROM processing_jobs
GROUP BY status;

SELECT
    original_filename,
    original_object_key,
    thumbnail_small_key,
    thumbnail_large_key
FROM images
LIMIT 10;

SELECT
    status,
    COUNT(*) AS total_events
FROM outbox_events
GROUP BY status;

SELECT
    a.name AS album_name,
    i.original_filename,
    i.status AS image_status,
    j.status AS job_status,
    i.original_object_key
FROM albums a
JOIN images i
    ON a.id = i.album_id
LEFT JOIN processing_jobs j
    ON i.id = j.image_id
WHERE i.is_test_data = TRUE
ORDER BY i.created_at
LIMIT 20;

-- Ghi nhận một sự kiện đã xử lý
INSERT INTO processed_events (
    event_id,
    idempotency_key,
    event_type
)
VALUES (
    'test-event-001',
    'image-processing-001',
    'IMAGE_PROCESSED'
)
ON CONFLICT DO NOTHING;

-- Chạy lại cùng sự kiện
INSERT INTO processed_events (
    event_id,
    idempotency_key,
    event_type
)
VALUES (
    'test-event-001',
    'image-processing-001',
    'IMAGE_PROCESSED'
)
ON CONFLICT DO NOTHING;

-- Kiểm tra kết quả
SELECT *
FROM processed_events
WHERE idempotency_key = 'image-processing-001';
