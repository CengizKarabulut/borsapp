ALTER TABLE command_jobs ADD COLUMN IF NOT EXISTS context JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE command_jobs ADD COLUMN IF NOT EXISTS request_key TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS ix_command_jobs_request_key ON command_jobs(request_key) WHERE request_key IS NOT NULL;
