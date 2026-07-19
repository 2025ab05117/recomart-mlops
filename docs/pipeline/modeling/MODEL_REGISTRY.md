# Model Registry

## Purpose

The registry provides durable model identity, run lineage, and metric history.
MLflow remains the experiment and artifact system; the relational registry is
the queryable governance layer.

## SQL deliverables

- `sql/model_registry/001_model_registry.sql` creates `model_registry`.
- `sql/model_registry/002_model_runs.sql` creates `model_runs`,
  `model_metrics`, foreign keys, and retrieval indexes.

Scripts are additive and idempotent (`IF NOT EXISTS`). Normal initialization
does not drop or truncate data.

## Tables

### model_registry

One row per named model version. It stores model identity, algorithm,
deployment stage, artifact URI, persisted path, and timestamps. The
`(model_name, model_version)` pair is unique.

### model_runs

One row per algorithm training run. It links registry identity to the source
training batch, feature batch, MLflow run and experiment, configuration hash,
Git commit, duration, status, and structured metadata.

### model_metrics

One row per run, metric, and dataset split. `top_k` identifies ranking cutoff
where applicable. Keeping metrics normalized allows comparison across versions
without parsing JSON artifacts.

## Versioning and promotion

Model artifacts are immutable per `model_run_id`. Register a new version for a
changed configuration, data lineage, or algorithm. Promotion changes the
registry stage (`NONE`, `STAGING`, `PRODUCTION`, or `ARCHIVED`) after review;
it does not rewrite the underlying artifact.

## Example queries

Latest successful runs:

```sql
SELECT model_run_id, algorithm, feature_batch_id, completed_at
FROM model_runs
WHERE status = 'SUCCESS'
ORDER BY completed_at DESC;
```

Compare Precision@10:

```sql
SELECT r.algorithm, m.metric_value
FROM model_runs AS r
JOIN model_metrics AS m USING (model_run_id)
WHERE m.metric_name = 'precision_at_10'
  AND m.dataset_split = 'test'
ORDER BY m.metric_value DESC;
```

Production models:

```sql
SELECT model_name, model_version, algorithm, artifact_uri
FROM model_registry
WHERE stage = 'PRODUCTION';
```

## Recommendation interfaces

The collaborative model exposes `recommend(user_id, top_k)` and returns
`product_id`, `score`, and `rank`. The content model exposes
`similar_items(product_id, top_k)` with the same output schema and also
supports user-profile recommendations for evaluation. API layers may wrap
these methods but must not contain training or recommendation business logic.
