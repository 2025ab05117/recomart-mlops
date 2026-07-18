# Ingestion Execution Guide

## Prerequisites

- Python 3.12;
- dependencies from `requirements.txt`;
- generated authoritative files under `data/incoming/`;
- an active popularity API for a complete run;
- AWS/MinIO credentials only when using S3 mode.

Install project dependencies in the active virtual environment:

```powershell
python -m pip install -r requirements.txt
```

## Start the Popularity API

From the repository root:

```powershell
python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

Verify it without exposing credentials:

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/popularity?limit=2
```

The endpoint reads generated source artifacts from `data/incoming`. Override
that directory with `RECOMART_INCOMING_PATH` when required.

## Default Local Execution

With the API running:

```powershell
python -m src.ingestion.cli
```

Defaults are:

- storage: `local`;
- input: `data/incoming`;
- output: `data/raw`;
- API: `http://localhost:8000/api/v1/popularity`;
- log level: `INFO`.

Explicit local execution:

```powershell
python -m src.ingestion.cli `
  --storage local `
  --input-path data/incoming `
  --output-path data/raw
```

Use a controlled batch identifier when rerun behavior must be inspected:

```powershell
python -m src.ingestion.cli --batch-id RECO_DEMO_001
```

A completed raw batch is immutable. Use a new batch ID when source content has
changed.

## AWS S3 Execution

Configure credentials through the standard AWS chain, then run:

```powershell
python -m src.ingestion.cli `
  --storage s3 `
  --bucket recomart-data `
  --prefix raw `
  --region ap-south-1
```

An optional named profile is supported:

```powershell
python -m src.ingestion.cli `
  --storage s3 `
  --bucket recomart-data `
  --profile recomart
```

## MinIO Execution

MinIO uses the S3 adapter and standard AWS environment variable names:

```powershell
$env:AWS_ACCESS_KEY_ID = "<minio-access-key>"
$env:AWS_SECRET_ACCESS_KEY = "<minio-secret-key>"

python -m src.ingestion.cli `
  --storage s3 `
  --bucket recomart-data `
  --prefix raw `
  --endpoint-url http://localhost:9000
```

Never pass access keys as CLI arguments.

## Supported Environment Variables

### Credentials and AWS Chain

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_SESSION_TOKEN`
- `AWS_DEFAULT_REGION`
- `AWS_PROFILE`

### RecoMart Settings

- `RECOMART_STORAGE_TYPE`
- `RECOMART_INPUT_PATH`
- `RECOMART_RAW_PATH`
- `RECOMART_POPULARITY_API_URL`
- `RECOMART_INCOMING_PATH`
- `RECOMART_S3_BUCKET`
- `RECOMART_S3_PREFIX`
- `RECOMART_S3_ENDPOINT_URL`
- `RECOMART_LOG_LEVEL`
- `RECOMART_INGESTION_LOG_DIRECTORY`

`.env.example` contains placeholders only. The application does not
automatically load `.env`; inject variables through the shell, deployment
platform, Airflow secret backend, or another approved secret manager.

## Configuration Precedence

The resolution order is:

```text
command-line arguments
→ environment variables
→ configs/ingestion.yaml
→ built-in defaults
```

CLI values are intended for one execution. Environment values are useful for
deployment. YAML contains non-secret versioned behavior. Built-in values are
safe fallbacks.

## Logs

Console logs and rotating JSON-line file logs contain the same operational
events. The default file is:

```text
logs/ingestion/ingestion.log
```

Inspect recent entries:

```powershell
Get-Content logs/ingestion/ingestion.log -Tail 20
```

Useful fields include `batch_id`, `run_id`, `correlation_id`, `source_type`,
`dataset_type`, `operation`, `status`, `retry_attempt`, and `duration_ms`.
Credential values are redacted and must never be copied into log messages.

## Verify a Manifest

Locate manifests locally:

```powershell
Get-ChildItem data/raw/manifests -Recurse -Filter ingestion_manifest.json
```

Inspect a selected manifest:

```powershell
Get-Content "<manifest-path>" | ConvertFrom-Json
```

Confirm:

- `status` is `SUCCESS`;
- five source records are present;
- every record contains destination, count, size, and SHA-256;
- the API record contains HTTP status, request URL, and retry count;
- `errors` is empty.

For S3:

```powershell
aws s3 cp `
  s3://recomart-data/raw/manifests/<partitions>/ingestion_manifest.json `
  -
```

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | Every required source succeeded or was idempotently present |
| `1` | Configuration, initialization, or terminal manifest failure |
| `2` | Run completed with `PARTIAL_SUCCESS` or `FAILED` source status |

Schedulers must treat any non-zero result as a failed task requiring review.

## Airflow Scheduling

The runner performs one batch and exits. A thin Airflow task may invoke it each
day at 01:00 UTC using:

```text
0 1 * * *
```

The DAG owns schedule, timeout, task retry, and dependency wiring only.
Ingestion behavior remains in `src/ingestion/`.

## Troubleshooting

- Missing file: regenerate or restore the required incoming source; do not
  bypass it.
- API 4xx: fix URL, authorization, or query; permanent client errors are not
  retried.
- API timeout/5xx: review structured retry logs and service health.
- S3 access denied: verify the standard credential chain and least-privilege
  bucket policy.
- S3 bucket missing: create or correctly configure the bucket.
- Immutable conflict: use the original content or create a new batch ID; never
  overwrite raw data.
