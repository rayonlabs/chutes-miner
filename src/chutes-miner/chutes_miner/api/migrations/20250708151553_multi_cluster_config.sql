-- migrate:up
ALTER TABLE servers ADD COLUMN IF NOT EXISTS kubeconfig TEXT;
ALTER TABLE servers ADD COLUMN IF NOT EXISTS agent_api TEXT;

-- migrate:down
ALTER TABLE servers DROP COLUMN IF EXISTS agent_api;
ALTER TABLE servers DROP COLUMN IF EXISTS kubeconfig;