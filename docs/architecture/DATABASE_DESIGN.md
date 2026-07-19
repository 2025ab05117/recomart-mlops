# PostgreSQL Database Design

## Purpose

PostgreSQL is the operational metadata and lineage store. It records what the
pipeline processed and produced. Large analytical datasets and binary artifacts
belong in S3-compatible storage, not database columns.

## Design Conventions

- Tables and columns use `snake_case`.
- Primary keys use UUIDs unless a stable natural key is explicitly appropriate.
- All timestamps are timezone-aware and stored in UTC.
- Tables include `created_at` and, for mutable control records, `updated_at`.
- Enumerated states are constrained by database checks or managed reference tables.
- Foreign keys enforce metadata integrity.
- JSONB is reserved for extensible, queryable metadata; core fields remain typed.
- Checksums use SHA-256 and a consistent lowercase hexadecimal representation.

## Core Tables

### `batches`

Tracks generator submissions. Core fields include `batch_id`, source, dataset
edition, manifest URI and checksum, correlation ID, created time, current state,
and optional failure code. State transitions are controlled and auditable.

### `pipeline_runs`

Represents one end-to-end or scoped execution. Fields include `run_id`,
`batch_id`, DAG/run identifiers, trigger type, code version, configuration
version, start/end times, status, and error summary.

### `task_runs`

Captures stage-level execution attempts, including task name, attempt number,
status, timestamps, input/output counts, and sanitized error information. The
Airflow metadata database is not a substitute for this domain record.

### `data_assets`

Indexes immutable datasets and artifacts. Fields include asset ID, layer,
entity, URI, format, schema version, dataset version, checksum, size, record
count, partition metadata, batch ID, producer run ID, and commit timestamp.

### `validation_runs` and `validation_results`

Store validation outcome, thresholds, total/valid/rejected counts, and
rule-level results. Rule results contain rule ID, severity, status, observed and
expected values, affected count, and optional bounded diagnostic metadata.

### `feature_definitions`

Stores feature name, entity type, definition version, data type, description,
owner, transformation reference, time semantics, and lifecycle status.

### `feature_materializations`

Links a set of definitions to an output asset, source prepared assets, as-of
time, record count, code/config versions, and materialization status.

### `lineage_edges`

Represents a directed edge from an input asset to an output asset for a run and
transformation. Duplicate edges are prevented by an appropriate composite
unique constraint.

### `model_runs`

Links feature materialization, split definition, MLflow experiment/run,
algorithm, model artifact, metrics summary, code version, random seed, status,
and training timestamps.

### `model_versions`

Tracks registered versions, model-run source, stage or alias, approval status,
promotion metadata, and retirement state. Promotion history must be retained.

### `reports`

Indexes report type, report version, artifact URI/checksum, source run or model
version, generation time, and publication status.

## Relationships

```text
batches 1 ── * pipeline_runs 1 ── * task_runs
   |              |
   |              └── * data_assets
   |                       |
   └── * validation_runs    ├── * lineage_edges (input/output)
                |           ├── * feature_materializations
                └── * validation_results

feature_materializations 1 ── * model_runs 1 ── * model_versions
pipeline_runs/model_versions 1 ── * reports
```

Exact optionality is finalized in migrations, but no lineage edge may reference
a nonexistent asset.

## Transactions and Concurrency

- Claiming a batch is atomic and prevents two active processors.
- State updates use allowed transitions and optimistic locking where useful.
- Asset registration and successful stage status are committed together after
  the object-store commit succeeds.
- Transactions must not remain open during uploads, model training, or remote calls.
- Database retries are limited to transient connection or serialization errors.

Cross-system operations cannot be one atomic transaction. Reconciliation relies
on immutable objects, commit markers, idempotency keys, and repeatable metadata
registration.

## Indexing

Indexes support common access paths:

- batch state and creation time;
- run status, batch ID, and start time;
- asset layer/entity/version and batch/run ID;
- validation run and rule ID;
- lineage input/output asset;
- feature name/version and materialization as-of time;
- MLflow run ID and model status;
- report source and type.

Indexes are justified by queries and measured. Avoid indexing low-selectivity
fields alone without evidence.

## Migrations

All schema changes are versioned, ordered, repeatable across environments, and
reviewed. A migration must define forward behavior and, where safe, rollback
behavior. Production startup must not silently create or mutate schemas.
Destructive changes require staged migration and explicit approval.

## Database Access Rules

Application code uses repository interfaces and parameterized statements.
Credentials and connection URLs come from environment variables. Connection
pools have bounded sizes and timeouts. Repository methods translate driver
errors into meaningful application exceptions while preserving the original
cause for logs.

## Data Protection and Retention

Do not store raw credentials, access tokens, or large row samples. Diagnostic
payloads are bounded and sanitized. Database roles are separated for migrations,
pipeline writes, and read-only reporting. Backup and restore procedures must be
tested for any deployment presented as persistent.
