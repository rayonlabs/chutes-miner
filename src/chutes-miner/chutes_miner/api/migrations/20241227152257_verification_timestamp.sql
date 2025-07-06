-- migrate:up
ALTER TABLE deployments ADD COLUMN IF NOT EXISTS verified_at TIMESTAMP;
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'deployments' AND column_name = 'verified'
    ) THEN
        UPDATE deployments SET verified_at = CURRENT_TIMESTAMP WHERE verified = true;
    END IF;
END $$;
ALTER TABLE deployments DROP COLUMN IF EXISTS verified;

-- migrate:down
ALTER TABLE deployments ADD COLUMN IF NOT EXISTS verified BOOLEAN;
UPDATE deployments SET verified = true WHERE verified_at IS NOT NULL;
ALTER TABLE deployments DROP COLUMN IF EXISTS verified_at;
