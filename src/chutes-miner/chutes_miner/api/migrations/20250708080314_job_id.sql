-- migrate:up
ALTER TABLE deployments ADD COLUMN IF NOT EXISTS job_id TEXT;

-- migrate:down
ALTER TABLE deployments DROP COLUMN IF EXISTS job_id;
