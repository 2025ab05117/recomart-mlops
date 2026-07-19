# Pipeline Recovery Guide

## Retry One Failed Task

Inspect its application manifest and Airflow log, then use Grid → task instance
→ Clear. Airflow reuses XCom values from the same DAG run and therefore the same
batch context. Stage-level checksum and conflict rules remain authoritative.

## Resume From Validation

Clear `validate_data` and all downstream tasks. Do not clear ingestion unless
its manifest or raw assets are incomplete. The resolved `batch_id` remains
unchanged.

## Full New Run

Trigger the DAG without `batch_id`. With `run_generator=true`, incoming data is
regenerated and ingestion creates a new batch.

## Reprocess Existing Data

Trigger:

```json
{
  "run_generator": false,
  "batch_id": "RECO_..."
}
```

Never change the batch ID midway through a run.

## Validation Failure

Technical failure requires correction of missing/unreadable input or
configuration. Quality issues can proceed in non-strict mode. In strict mode,
repair the source through the appropriate earlier stage and create a new
immutable batch; do not edit raw data.

## Database Failure

Verify `RECOMART_DATABASE_URL`, credentials, connectivity, and database
permissions. Feature persistence is transactional and will not mark a partial
batch successful. Clear the feature task and downstream tasks after recovery.

## Model Failure

Confirm the feature gate passed, required splits are non-empty, and local MLflow
storage or the remote tracking server is writable. Clear model training,
lineage finalization, and summary tasks.

## Idempotency Conflict

Do not overwrite immutable artifacts. Compare the current stage manifest,
configuration hash, input checksums, and supplied batch ID. Use a new batch/run
when inputs or configuration are intentionally different.

## Pre-Retry Checklist

1. Read the failed task log and structured failure JSON.
2. Inspect the producing and consuming manifests.
3. Verify checksums and status fields.
4. Confirm external API/database/MLflow availability.
5. Clear only the failed task and required downstream tasks.
