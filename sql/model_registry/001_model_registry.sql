-- RecoMart PostgreSQL model registry.
CREATE TABLE IF NOT EXISTS model_registry (
    model_id UUID PRIMARY KEY,
    model_name VARCHAR(100) NOT NULL,
    algorithm VARCHAR(100) NOT NULL,
    model_version VARCHAR(50) NOT NULL,
    stage VARCHAR(30) NOT NULL DEFAULT 'NONE',
    artifact_uri TEXT NOT NULL,
    model_path TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (model_name, model_version)
);

CREATE INDEX IF NOT EXISTS ix_model_registry_name_stage
    ON model_registry (model_name, stage);
