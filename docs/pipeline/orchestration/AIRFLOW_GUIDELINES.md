# Apache Airflow Guidelines

## Role of Airflow

Airflow is the RecoMart scheduler and orchestrator. It decides when work runs,
passes identifiers, applies execution policy, and displays status. All data
validation, transformation, feature calculation, model training, and reporting
logic belongs under `src/`.

## DAG Responsibilities

A DAG may define:

- schedule, start date, catchup, tags, and ownership;
- task dependencies and task groups;
- retry count, delay, timeout, and execution pool;
- small typed parameters and identifiers;
- calls to stable application-service entry points;
- success/failure callbacks that publish operational events.

A DAG must not contain:

- DataFrame transformations or validation rules;
- raw SQL implementing business behavior;
- direct model fitting or feature calculations;
- hardcoded credentials, bucket names, or environment endpoints;
- large payloads passed through XCom;
- network access or file reads at DAG parse time.

## DAG Design

Use one clear workflow for the canonical pipeline or a small set of explicitly
composed workflows. Task names describe business stages, such as
`validate_raw_batch`, not implementation mechanisms. Dependencies mirror the
required layer order and must not allow downstream execution after a failed
quality gate.

Dynamic task mapping is permitted for bounded entity or partition lists.
Unbounded fan-out must be controlled through pools or chunking.

## Parse-Time Safety

DAG modules must import quickly and deterministically. Creating SDK clients,
querying PostgreSQL, listing S3 objects, loading datasets, or contacting MLflow
during import is prohibited. Environment-specific configuration is resolved
within task execution or through safe Airflow configuration references.

## Data Passing

XCom contains only small serializable values:

- batch and run identifiers;
- asset IDs or S3 URIs;
- status/result summaries;
- counts and version identifiers.

Datasets, DataFrames, model binaries, manifests of unbounded size, and secrets
must not be placed in XCom. Tasks exchange bulk data through committed S3
objects and PostgreSQL metadata.

## Idempotency and Retries

Each task calls an idempotent application service. A retry detects a previously
committed matching output and returns it. Retry policy is based on error class:

- transient object-store, database connection, or service errors: bounded retry;
- validation failure, malformed configuration, authorization, or checksum
  conflict: fail without blind retry;
- resource exhaustion: fail with useful diagnostics and apply an operational fix.

Use exponential backoff and execution timeouts. Do not implement manual retry
loops in DAG code when Airflow owns the retry policy.

## Scheduling and Catchup

Schedules are explicit and timezone-aware. Start dates are fixed, never computed
relative to the current import time. Catchup behavior is explicitly selected.
Data intervals and logical dates are used for partitions; wall-clock execution
time is recorded separately.

Manual and backfill runs require an explicit batch, date interval, or controlled
selection criterion. Backfills create new immutable output versions.

## Concurrency

Pools limit access to PostgreSQL, object storage, and training resources.
Per-DAG and per-task concurrency settings prevent duplicate batch processing and
resource saturation. Batch claiming in PostgreSQL remains the authoritative
concurrency guard.

## Failure and Notifications

Task failures record sanitized context including DAG ID, task ID, Airflow run ID,
application run ID, batch ID, attempt, error category, and relevant asset ID.
Callbacks must be lightweight and failure-safe. Notification failure must not
hide the original task failure.

Data-quality failure produces a failed or quarantined business status with a
validation report; it is not converted into success solely to keep a DAG green.

## Connections and Secrets

Secrets use Airflow Connections backed by environment variables or an approved
secret backend. DAG source must not contain credentials. Connection IDs may be
configured, but application services should receive resolved, narrow settings
or use standard environment-based configuration consistently.

## Testing

- Import tests verify that all DAGs form a valid bag without side effects.
- Structure tests verify expected task IDs and dependency ordering.
- Unit tests mock application-service entry points.
- Integration tests execute representative tasks against disposable services.
- A small end-to-end test verifies the complete layer sequence.

## Deployment

DAG changes are version-controlled and reviewed with the corresponding `src/`
interfaces. Workers use the same application package version recorded in run
metadata. Scheduler and worker clocks use UTC, while display timezone may be
configured separately.
