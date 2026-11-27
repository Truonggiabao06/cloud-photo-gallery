
-- =====================================================
-- PROJECT: CLOUD PHOTO GALLERY
-- MEMBER 4: DATABASE & STORAGE ARCHITECT
-- DATABASE: PostgreSQL
-- =====================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- =====================================================
-- TABLE 1: ALBUMS
-- Quản lý album ảnh
-- =====================================================

CREATE TABLE IF NOT EXISTS albums (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    owner_id VARCHAR(255) NOT NULL,
    name VARCHAR(150) NOT NULL,
    description TEXT,

    visibility VARCHAR(20) NOT NULL DEFAULT 'PRIVATE'
        CHECK (visibility IN ('PRIVATE', 'SHARED')),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_album_name
        CHECK (length(trim(name)) > 0)
);


-- =====================================================
-- TABLE 2: ALBUM_MEMBERS
-- Quản lý quyền chia sẻ album
-- =====================================================

CREATE TABLE IF NOT EXISTS album_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    album_id UUID NOT NULL
        REFERENCES albums(id) ON DELETE CASCADE,

    member_id VARCHAR(255) NOT NULL,

    member_role VARCHAR(20) NOT NULL DEFAULT 'VIEWER'
        CHECK (member_role IN ('VIEWER', 'EDITOR')),

    invited_by VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_album_member
        UNIQUE (album_id, member_id)
);


-- =====================================================
-- TABLE 3: IMAGES
-- Quản lý ảnh gốc và ảnh thumbnail
-- =====================================================

CREATE TABLE IF NOT EXISTS images (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    album_id UUID NOT NULL
        REFERENCES albums(id) ON DELETE CASCADE,

    owner_id VARCHAR(255) NOT NULL,

    original_filename VARCHAR(255) NOT NULL,

    mime_type VARCHAR(100) NOT NULL,

    file_size BIGINT NOT NULL
        CHECK (file_size > 0),

    -- Khóa ảnh gốc: được cung cấp khi upload
    original_object_key TEXT NOT NULL UNIQUE,

    -- Khóa thumbnail được xác định tự động
    -- Không thay đổi khi Worker chạy lại
    thumbnail_small_key TEXT
        GENERATED ALWAYS AS
        ('thumbnails/' || id::TEXT || '/small.webp') STORED,

    thumbnail_large_key TEXT
        GENERATED ALWAYS AS
        ('thumbnails/' || id::TEXT || '/large.webp') STORED,

    checksum_sha256 VARCHAR(64),

    status VARCHAR(20) NOT NULL DEFAULT 'UPLOADED'
        CHECK (status IN (
            'UPLOADED',
            'PENDING',
            'PROCESSING',
            'COMPLETED',
            'FAILED'
        )),

    error_message TEXT,

    is_test_data BOOLEAN NOT NULL DEFAULT FALSE,

    test_case VARCHAR(20) DEFAULT 'NORMAL'
        CHECK (test_case IN (
            'NORMAL',
            'CORRUPTED',
            'UNSUPPORTED'
        )),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ,

    CONSTRAINT chk_checksum
        CHECK (
            checksum_sha256 IS NULL
            OR checksum_sha256 ~ '^[a-fA-F0-9]{64}$'
        )
);


-- =====================================================
-- TABLE 4: PROCESSING_JOBS
-- Theo dõi công việc xử lý ảnh
-- =====================================================

CREATE TABLE IF NOT EXISTS processing_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    image_id UUID NOT NULL UNIQUE
        REFERENCES images(id) ON DELETE CASCADE,

    status VARCHAR(20) NOT NULL DEFAULT 'QUEUED'
        CHECK (status IN (
            'QUEUED',
            'PROCESSING',
            'COMPLETED',
            'FAILED'
        )),

    retry_count INTEGER NOT NULL DEFAULT 0
        CHECK (retry_count >= 0),

    max_retries INTEGER NOT NULL DEFAULT 3
        CHECK (max_retries >= 0),

    worker_id VARCHAR(255),

    locked_until TIMESTAMPTZ,

    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,

    last_error TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- =====================================================
-- TABLE 5: PROCESSED_EVENTS
-- Chống xử lý sự kiện trùng lặp
-- =====================================================

CREATE TABLE IF NOT EXISTS processed_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    event_id VARCHAR(255) NOT NULL UNIQUE,

    idempotency_key VARCHAR(255) NOT NULL UNIQUE,

    image_id UUID
        REFERENCES images(id) ON DELETE SET NULL,

    event_type VARCHAR(100) NOT NULL,

    payload JSONB,

    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- =====================================================
-- TABLE 6: OUTBOX_EVENTS
-- Lưu sự kiện trước khi gửi vào Queue
-- =====================================================

CREATE TABLE IF NOT EXISTS outbox_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    aggregate_type VARCHAR(100) NOT NULL,

    aggregate_id UUID NOT NULL,

    event_type VARCHAR(100) NOT NULL,

    payload JSONB NOT NULL,

    status VARCHAR(20) NOT NULL DEFAULT 'PENDING'
        CHECK (status IN (
            'PENDING',
            'PROCESSING',
            'PUBLISHED',
            'FAILED'
        )),

    attempts INTEGER NOT NULL DEFAULT 0
        CHECK (attempts >= 0),

    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    locked_at TIMESTAMPTZ,

    published_at TIMESTAMPTZ,

    last_error TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- =====================================================
-- INDEXES
-- Tăng tốc độ truy vấn
-- =====================================================

CREATE INDEX IF NOT EXISTS idx_albums_owner
ON albums(owner_id);

CREATE INDEX IF NOT EXISTS idx_album_members_member
ON album_members(member_id);

CREATE INDEX IF NOT EXISTS idx_images_album
ON images(album_id);

CREATE INDEX IF NOT EXISTS idx_images_owner
ON images(owner_id);

CREATE INDEX IF NOT EXISTS idx_images_status
ON images(status);

CREATE INDEX IF NOT EXISTS idx_processing_status
ON processing_jobs(status);

CREATE INDEX IF NOT EXISTS idx_processing_locked
ON processing_jobs(locked_until);

CREATE INDEX IF NOT EXISTS idx_processed_image
ON processed_events(image_id);

CREATE INDEX IF NOT EXISTS idx_outbox_pending
ON outbox_events(available_at, created_at)
WHERE status = 'PENDING';

CREATE INDEX IF NOT EXISTS idx_outbox_aggregate
ON outbox_events(aggregate_id);


-- =====================================================
-- TRIGGER 1: AUTOMATICALLY UPDATE updated_at
-- =====================================================

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


DROP TRIGGER IF EXISTS trg_albums_updated
ON albums;

CREATE TRIGGER trg_albums_updated
BEFORE UPDATE ON albums
FOR EACH ROW
EXECUTE FUNCTION update_updated_at();


DROP TRIGGER IF EXISTS trg_images_updated
ON images;

CREATE TRIGGER trg_images_updated
BEFORE UPDATE ON images
FOR EACH ROW
EXECUTE FUNCTION update_updated_at();


DROP TRIGGER IF EXISTS trg_jobs_updated
ON processing_jobs;

CREATE TRIGGER trg_jobs_updated
BEFORE UPDATE ON processing_jobs
FOR EACH ROW
EXECUTE FUNCTION update_updated_at();


-- =====================================================
-- TRIGGER 2: PROTECT ORIGINAL OBJECT KEY
-- Không cho phép thay đổi đường dẫn ảnh gốc
-- =====================================================

CREATE OR REPLACE FUNCTION prevent_original_key_change()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.original_object_key
       IS DISTINCT FROM OLD.original_object_key THEN

        RAISE EXCEPTION
        'Original object key is immutable and cannot be changed';

    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


DROP TRIGGER IF EXISTS trg_immutable_original_key
ON images;

CREATE TRIGGER trg_immutable_original_key
BEFORE UPDATE OF original_object_key ON images
FOR EACH ROW
EXECUTE FUNCTION prevent_original_key_change();


COMMIT;

SELECT
    table_name
FROM information_schema.tables
WHERE table_schema = 'public'
AND table_type = 'BASE TABLE'
ORDER BY table_name;
