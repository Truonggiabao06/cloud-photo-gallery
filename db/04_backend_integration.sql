BEGIN;

ALTER TABLE images ADD COLUMN IF NOT EXISTS progress SMALLINT NOT NULL DEFAULT 0
    CHECK (progress BETWEEN 0 AND 100);
UPDATE images SET progress = 100 WHERE status = 'COMPLETED' AND progress <> 100;

ALTER TABLE outbox_events ADD COLUMN IF NOT EXISTS lease_id UUID;
ALTER TABLE outbox_events ADD COLUMN IF NOT EXISTS pubsub_message_id TEXT;
CREATE INDEX IF NOT EXISTS idx_outbox_processing_lease ON outbox_events (locked_at)
    WHERE status = 'PROCESSING';

COMMIT;
