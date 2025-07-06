-- migrate:up
ALTER TABLE chutes ADD COLUMN IF NOT EXISTS ban_reason TEXT;

-- migrate:down
ALTER TABLE chutes DROP COLUMN IF EXISTS ban_reason;
