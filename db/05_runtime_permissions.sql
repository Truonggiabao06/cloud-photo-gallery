BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'photo_runtime') THEN
        CREATE ROLE photo_runtime NOLOGIN;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO photo_runtime;
GRANT SELECT, INSERT, UPDATE ON albums, album_members, images, processing_jobs, outbox_events TO photo_runtime;
GRANT SELECT, INSERT ON processed_events TO photo_runtime;

COMMIT;
