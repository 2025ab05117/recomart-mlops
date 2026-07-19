# Ingestion Design

## Purpose and Scope

RecoMart ingestion moves generated source data from the incoming layer to an
immutable raw layer. It implements Assignment Part 2 (data collection and
ingestion) and Part 3 (raw data storage). One invocation performs one bounded
batch and exits; scheduling belongs to Airflow.

The ingestion path is:

```text
data/incoming files ─┐
                     ├─> ingestion runner ─> local or S3 raw storage
popularity REST API ─┘                         └─> ingestion manifest
```

No validation, cleaning, schema conversion, feature engineering, or model logic
is performed here. CSV remains CSV, JSON remains JSON, and source bytes are
preserved.

## Components

### File Ingestion

`src.ingestion.file_ingestion.FileIngestionService` handles the four required
files:

- `users.csv`
- `products.json`
- `clickstream.csv`
- `purchasehistory.csv`

For each file it verifies existence and readability, calculates SHA-256,
counts records, builds the canonical raw partition, publishes through the
storage interface, and returns manifest metadata. CSV counting excludes the
header. JSON input must be a top-level array. A missing required source is an
explicit `SourceFileNotFoundError` and is never silently skipped or retried.

### REST API Ingestion

`src.ingestion.api_ingestion.PopularityApiIngestionService` retrieves product
popularity strictly through HTTP. It does not read `popularity.json` directly.
The default source is:

```text
GET http://localhost:8000/api/v1/popularity
```

The HTTP response must be a JSON array whose records contain:

- `product_id`
- `average_rating`
- `total_ratings`
- `popularity_score`
- `trend`
- `updated_at`

The complete successful response bytes are checksummed and written as
`popularity.json` under the API raw partition.

### Popularity Source API

`src.api.main` exposes `GET /api/v1/popularity`. The route is thin and delegates
to `PopularityService`, which joins generated `products.json` aggregate rating
fields with generated `popularity.json` scores and trends. Supported query
parameters are:

- `limit`: 1–10,000;
- `offset`: zero or greater;
- `updated_after`: ISO 8601 timestamp.

The source directory can be overridden with `RECOMART_INCOMING_PATH`.

### Storage Abstraction

`RawStorage` is the provider-neutral contract used by ingestion services. It
supports:

- `build_destination`;
- `exists`;
- `write_file`;
- `write_bytes`.

`LocalStorage` writes under a configured filesystem root. `S3Storage` writes to
AWS S3, MinIO, or another S3-compatible service. File and API services contain
no provider-specific logic.

Both implementations use the same relative path. Provider-specific differences
are restricted to local absolute paths versus `s3://` URIs.

## Idempotency and Immutability

Each destination is identified by source, dataset, UTC ingestion date/hour, and
batch ID. Before publication:

1. the source or response checksum is calculated;
2. storage checks the destination;
3. a matching existing checksum returns `IDEMPOTENT_SUCCESS`;
4. a different checksum raises `StorageConflictError`;
5. a new object is written and verified.

Local writes use a same-directory temporary file and exclusive publication.
S3 uploads store SHA-256 in object metadata. Existing S3 objects must provide a
matching `sha256` metadata value. Raw objects are never overwritten.

The manifest is the batch commit record and is written only after all configured
sources have been attempted. A successful rerun of a finalized batch reuses the
existing manifest after every source object has passed idempotency checks.

## Manifest

One `ingestion_manifest.json` records:

- manifest version;
- batch, run, and correlation IDs;
- UTC start and completion timestamps;
- aggregate status;
- source and destination;
- per-source counts, sizes, checksums, destinations, and status;
- HTTP status, safe request URL, records received, and retry count for API data;
- classified error entries.

Aggregate states are:

- `SUCCESS`: every source succeeded or was idempotently present;
- `PARTIAL_SUCCESS`: at least one source succeeded and at least one failed;
- `FAILED`: no source succeeded.

The CLI returns zero only for `SUCCESS`, so partial data cannot be mistaken for
a complete ingestion.

## Retry Strategy

Retries are bounded and externally configured in `configs/ingestion.yaml`.

HTTP retries apply to request/connection errors and statuses 408, 429, 500, 502,
503, and 504. Permanent client statuses such as 400, 401, 403, 404, and 422 are
not retried. Invalid JSON and schema violations are not retried. Default API
attempt delays are 1, 2, and 4 seconds.

S3 upload retries apply to timeouts, connection errors, throttling, and
temporary service errors. Authentication, authorization, bucket-not-found, and
immutable conflicts fail immediately. Local missing files and configuration
errors are never retried.

## Error Handling

The public error hierarchy distinguishes:

- `ConfigurationError`;
- `SourceFileNotFoundError`;
- `SourceFileReadError`;
- `ApiIngestionError`;
- `StorageWriteError`;
- `StorageConflictError`.

The runner records a failed source and continues attempting other sources so
successful metadata is preserved. Exceptions are logged at the boundary that
records the failure. Manifest publication failure is terminal because the batch
cannot be considered committed without its audit record.

## Structured Logging

Logs are emitted as one JSON object per line to:

1. the console;
2. `logs/ingestion/ingestion.log` through a rotating handler.

Configured fields include timestamp, severity, module, batch ID, run ID,
correlation ID, source, dataset, operation, status, retry attempt, duration, and
message. Credential values are never intentionally logged and configured AWS
credential values are defensively redacted.

## Configuration Precedence

Settings resolve in this order:

```text
command-line argument
→ environment variable
→ configs/ingestion.yaml
→ built-in safe default
```

AWS credentials are excluded from normal CLI arguments. Boto3 uses
`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, profiles,
workload roles, or the rest of its standard credential chain.

## Periodic Execution

The runner has no internal scheduler or infinite loop. A later Airflow DAG may
invoke the public runner once per task. A daily schedule at 01:00 UTC is:

```text
0 1 * * *
```

The DAG may select configuration, pass a batch ID, apply task timeout/retry
policy, and invoke the runner. It must not contain file verification, HTTP,
checksum, storage, or manifest business logic.
