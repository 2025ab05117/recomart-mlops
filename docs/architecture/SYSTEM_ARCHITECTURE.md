# System Architecture

## Architectural Style

RecoMart uses a layered batch architecture with ports and adapters. Pipeline
stages communicate through immutable S3 objects and PostgreSQL metadata rather
than hidden in-process state. Airflow supplies control flow; `src/` supplies
business behavior.

## Logical Architecture

```text
MovieLens source
      |
      v
FastAPI batch generator
      |
      v
S3 incoming -> raw -> validated -> prepared -> features -> models -> reports
                    ^                         |
                    |                         v
                Airflow orchestration     Feature Store
                    |                         |
                    +---- PostgreSQL metadata/lineage
                                              |
                                              v
                                      Training and MLflow
```

Validation is a gate between raw and validated publication. Lineage events span
all transitions, even though the diagram shows the primary data route.

## Components

### FastAPI Batch Generator

The API validates request parameters, delegates batch creation to a service,
uploads a batch and manifest to the incoming zone, and returns an accepted or
completed batch record. Routes must not manipulate DataFrames directly.
Requests use bounded batch sizes and idempotency keys.

### S3-Compatible Data Lake

The object store is the authoritative location for datasets and artifacts.
Objects are organized by layer, entity, processing date, batch, and version.
Publication uses write-then-commit semantics. Bucket names and endpoints come
from configuration.

### Apache Airflow

Airflow detects or receives batches, invokes application services in dependency
order, applies execution policies, and surfaces task status. It does not contain
validation rules, transformations, feature calculations, or modeling algorithms.

### Processing Services

Services under `src/` implement ingestion, validation, preparation, feature
engineering, materialization, training, and reporting. They accept typed inputs,
return explicit results, and use injected storage and metadata interfaces.

### PostgreSQL

PostgreSQL stores operational metadata: batches, runs, assets, quality results,
feature definitions/materializations, lineage edges, model records, and reports.
Bulk analytical datasets remain in object storage.

### Feature Store

The offline feature store publishes versioned user, item, and interaction
features. Each row carries entity keys and an event/as-of timestamp where
applicable. Definitions and materializations are registered in PostgreSQL.

### MLflow

MLflow records model parameters, metrics, dataset references, code/configuration
versions, and serialized artifacts. Models meeting promotion criteria may be
registered. MLflow is not the source of truth for pipeline batch status.

### Reporting

Reporting services consume registered validation and modeling results. Reports
are immutable artifacts in the reports layer and are indexed in PostgreSQL.

## Control Plane and Data Plane

The control plane consists of Airflow, PostgreSQL metadata, configuration, and
structured logs. The data plane consists of Parquet/JSON objects, feature
materializations, model artifacts, and reports.

Control records reference data-plane objects by URI, checksum, size, schema
version, and producer run. Large datasets must not be stored in PostgreSQL.

## Boundaries and Contracts

Every stage defines:

- accepted input layer and schema version;
- required identifiers and partition values;
- deterministic transformation behavior;
- output schema, format, and quality requirements;
- metadata and lineage records;
- error categories and retry behavior.

Contracts are versioned. Breaking schema changes require a new major schema
version and an explicit migration or compatibility path.

## Execution Semantics

1. A batch is assigned a unique `batch_id`.
2. Payload and manifest are uploaded to incoming.
3. A committed manifest makes the batch discoverable.
4. Airflow creates a pipeline `run_id` and locks or claims the batch.
5. Each stage writes temporary output, validates it, then publishes atomically.
6. Metadata and lineage are recorded after successful publication.
7. A terminal batch state is recorded as succeeded, failed, or quarantined.

Retries check for already committed outputs with matching checksums. Conflicting
outputs cause a failure rather than silent overwrite.

## Availability and Failure Isolation

- Object-store timeouts and transient errors may be retried with bounded backoff.
- Invalid data is quarantined and is not retried without a new decision or input.
- Database transactions are short and atomic.
- MLflow failure prevents model-stage completion but does not erase trained
  diagnostics.
- Reporting failure does not alter validated datasets or model artifacts.

## Security Architecture

Secrets are provided through environment variables or a deployment secret
manager. Services use TLS where supported. IAM/database roles follow least
privilege. Logs redact secrets and sensitive connection strings. Incoming file
names and metadata are treated as untrusted input and must not control local
filesystem paths or arbitrary S3 prefixes.

## Observability

Structured logs include service, environment, event name, severity, timestamp,
`correlation_id`, `batch_id`, `run_id`, and relevant artifact identifiers.
Metrics should cover throughput, latency, failure count, retry count, record
counts, rejected-record ratios, data freshness, and model quality. Health checks
must distinguish process liveness from dependency readiness.
