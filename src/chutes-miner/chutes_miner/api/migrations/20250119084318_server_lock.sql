-- migrate:up
ALTER TABLE servers ADD COLUMN IF NOT EXISTS locked BOOLEAN DEFAULT false;

-- migrate:down
ALTER TABLE servers DROP COLUMN IF EXISTS locked;
