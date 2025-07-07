-- migrate:up
ALTER TABLE chutes ADD COLUMN IF NOT EXISTS chutes_version TEXT;

-- migrate:down
ALTER TABLE chutes DROP COLUMN IF EXISTS chutes_version;
