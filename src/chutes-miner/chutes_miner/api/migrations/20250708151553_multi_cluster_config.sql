-- migrate:up
ALTER TABLE servers ADD COLUMN IF NOT EXISTS kubeconfig TEXT;

-- migrate:down
ALTER TABLE servers DROP COLUMN IF EXISTS kubeconfig;