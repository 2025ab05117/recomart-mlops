-- Reproducible model runs and metric history.
CREATE TABLE IF NOT EXISTS model_runs (
    model_run_id VARCHAR(80) PRIMARY KEY,
    model_id UUID REFERENCES model_registry(model_id),
    training_batch_id VARCHAR(80) NOT NULL,
    feature_batch_id VARCHAR(80) NOT NULL,
    mlflow_run_id VARCHAR(64),
    mlflow_experiment_id VARCHAR(64),
    algorithm VARCHAR(100) NOT NULL,
    configuration_hash CHAR(64) NOT NULL,
    git_commit VARCHAR(64),
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    status VARCHAR(30) NOT NULL,
    training_duration_seconds DOUBLE PRECISION,
    inference_duration_seconds DOUBLE PRECISION,
    metadata_json JSONB NOT NULL DEFAULT '{}'::JSONB,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS model_metrics (
    model_run_id VARCHAR(80) NOT NULL REFERENCES model_runs(model_run_id),
    metric_name VARCHAR(100) NOT NULL,
    metric_value DOUBLE PRECISION,
    dataset_split VARCHAR(30) NOT NULL DEFAULT 'test',
    top_k INTEGER,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (model_run_id, metric_name, dataset_split)
);

CREATE INDEX IF NOT EXISTS ix_model_runs_feature_batch
    ON model_runs (feature_batch_id);
CREATE INDEX IF NOT EXISTS ix_model_runs_status_completed
    ON model_runs (status, completed_at DESC);
CREATE INDEX IF NOT EXISTS ix_model_metrics_name
    ON model_metrics (metric_name);
