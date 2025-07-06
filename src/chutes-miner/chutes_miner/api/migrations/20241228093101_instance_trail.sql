-- migrate:up
CREATE TABLE deployment_audit (
    deployment_id TEXT PRIMARY KEY,
    validator TEXT NOT NULL,
    instance_id TEXT,
    chute_id TEXT NOT NULL,
    version TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    verified_at TIMESTAMP,
    deleted_at TIMESTAMP
);

CREATE INDEX idx_deployment_audit_ts ON deployment_audit (verified_at, deleted_at);

INSERT INTO deployment_audit (
   deployment_id,
   validator,
   instance_id,
   chute_id,
   version,
   created_at,
   verified_at
)
SELECT
   d.deployment_id,
   d.validator,
   d.instance_id,
   d.chute_id,
   d.version,
   d.created_at,
   d.verified_at
FROM deployments d;

-- Track when deployments are created.
CREATE OR REPLACE FUNCTION fn_deployment_audit_insert()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO deployment_audit (
        deployment_id,
        validator,
        chute_id,
        version
    ) VALUES (
        NEW.deployment_id,
        NEW.validator,
        NEW.chute_id,
        NEW.version
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Track when deployments are updated (verified).
CREATE OR REPLACE FUNCTION fn_deployment_audit_update()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.verified_at IS NOT NULL AND OLD.verified_at IS NULL THEN
        UPDATE deployment_audit
           SET verified_at = NEW.verified_at, instance_id = NEW.instance_id
         WHERE deployment_id = NEW.deployment_id
           AND verified_at IS NULL;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Function to handle deployment deletes
CREATE OR REPLACE FUNCTION fn_deployment_audit_delete()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE deployment_audit
       SET deleted_at = NOW()
     WHERE deployment_id = OLD.deployment_id
       AND deleted_at IS NULL;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

-- Create triggers
CREATE TRIGGER tr_deployment_audit_delete
    BEFORE DELETE ON deployments
    FOR EACH ROW
    EXECUTE FUNCTION fn_deployment_audit_delete();

CREATE TRIGGER tr_deployment_audit_insert
    AFTER INSERT ON deployments
    FOR EACH ROW
    EXECUTE FUNCTION fn_deployment_audit_insert();

CREATE TRIGGER tr_deployment_audit_update
    AFTER UPDATE ON deployments
    FOR EACH ROW
    EXECUTE FUNCTION fn_deployment_audit_update();

-- migrate:down
DROP TRIGGER IF EXISTS tr_deployment_audit_update ON deployments;
DROP TRIGGER IF EXISTS tr_deployment_audit_delete ON deployments;
DROP TRIGGER IF EXISTS tr_deployment_audit_insert ON deployments;
DROP FUNCTION IF EXISTS fn_deployment_audit_update;
DROP FUNCTION IF EXISTS fn_deployment_audit_delete;
DROP FUNCTION IF EXISTS fn_deployment_audit_insert;
DROP TABLE IF EXISTS deployment_audit;
