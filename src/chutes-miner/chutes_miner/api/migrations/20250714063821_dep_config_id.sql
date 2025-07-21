-- migrate:up
ALTER TABLE deployments ADD COLUMN IF NOT EXISTS config_id TEXT;

-- migrate:down
ALTER TABLE deployments DROP COLUMN IF EXISTS config_id;
