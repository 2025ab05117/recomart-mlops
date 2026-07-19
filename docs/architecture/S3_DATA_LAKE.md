# S3-Compatible Data Lake Design

## Purpose

AWS S3 or MinIO stores RecoMart datasets and artifacts. The design must work
against both providers without conditional business logic. Bucket names,
endpoints, regions, and credentials are external configuration.

## Storage Zones

Logical zones are:

- `incoming`: generator submissions awaiting ingestion;
- `raw`: immutable source-preserving records;
- `validated`: accepted records plus quarantine evidence;
- `prepared`: canonical analytical datasets;
- `features`: offline feature materializations;
- `models`: serialized models and model support artifacts;
- `reports`: published quality and model reports;
- `temporary`: uncommitted stage output with lifecycle expiry.

Zones may be separate buckets or prefixes. Code must consume logical zone names
resolved by configuration and must not embed physical bucket names.

## Object Key Convention

The standard pattern is:

```text
<zone>/<entity>/schema_version=<version>/processing_date=<YYYY-MM-DD>/
batch_id=<uuid>/run_id=<uuid>/part-<sequence>.<extension>
```

Only applicable partitions are included. Keys are lowercase, use forward
slashes, and contain sanitized values. Model and report keys add their immutable
artifact version. Temporary objects are stored under a run-scoped prefix.

## File Formats

- Tabular datasets: Parquet with PyArrow and a declared schema.
- Manifests and small metadata artifacts: UTF-8 JSON.
- Human-readable reports: HTML, Markdown, JSON, or PDF as configured.
- Model artifacts: format selected by the modeling contract, accompanied by
  metadata and a checksum.

CSV may be accepted in incoming but is converted to Parquet in raw. Downstream
layers must not depend on CSV inference.

## Manifest and Commit Protocol

Each published dataset version includes:

- data objects;
- `_manifest.json` describing all objects and checksums;
- `_SUCCESS` or an equivalent commit marker written last.

Readers must ignore a prefix without a valid commit marker. Writers upload to a
temporary prefix, verify size and checksum, copy or finalize objects into the
target version, create metadata, then commit. Failed temporary objects are
eligible for lifecycle cleanup.

## Immutability and Versioning

Incoming, raw, and published versions are append-only. Overwriting or deleting a
committed object is prohibited in normal application paths. Corrections create
a new version. Provider object versioning and retention should be enabled where
available, but application-level immutable keys remain mandatory.

## Storage Interface

Business services use an internal interface supporting:

- upload/download streaming;
- object existence and metadata lookup;
- bounded prefix listing with pagination;
- checksum verification;
- copy/finalize and commit operations;
- typed storage exceptions.

Provider SDK exceptions must not leak into domain logic. List operations must
not assume a single response page.

## Metadata

Object metadata or the corresponding PostgreSQL asset record contains media
type, content length, SHA-256 checksum, schema version, batch ID, run ID,
producer, and creation time. ETags are not treated as universal content
checksums because multipart uploads differ.

## Encryption and Access

- Use TLS for data in transit.
- Use provider-managed or customer-managed encryption at rest.
- Generator credentials may write only incoming objects.
- Pipeline workers read required upstream zones and write only their output zones.
- Report consumers receive read-only access to approved reports.
- Public bucket access is disabled.

Credentials come from environment variables or workload identity. They are
never placed in YAML, object keys, object metadata, logs, or manifests.

## Retention and Lifecycle

Retention is configured by environment and compliance needs. Temporary and
aborted multipart uploads receive short lifecycle expiry. Raw data is retained
long enough to reproduce all supported outputs. Feature, model, and report
versions are retained according to promotion and audit policy. Deletion is an
explicit administrative operation with an audit record.

## Failure Handling

Operations classify failures as transient, authorization, not-found, conflict,
or integrity errors. Transient errors use bounded exponential backoff with
jitter. Authorization and integrity failures are not blindly retried. Partial
uploads are aborted or left under temporary prefixes for cleanup.

## Local MinIO Compatibility

Local configuration may enable path-style addressing and a custom endpoint.
Production code must not assume MinIO-specific administrative APIs. Integration
tests should run the same storage contract suite against the selected
S3-compatible service.
