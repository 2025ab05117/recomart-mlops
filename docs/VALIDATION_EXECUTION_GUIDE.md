# RecoMart Validation Execution Guide

## Prerequisites

Use Python 3.12 and install `requirements.txt`. A successful ingestion manifest
and all five checksum-matching raw objects must exist. For the normal local
flow, first run the popularity API and ingestion as described in
`INGESTION_EXECUTION_GUIDE.md`.

## Commands

Validate the latest successful local batch:

```powershell
python -m src.validation.cli
```

Validate a specific batch:

```powershell
python -m src.validation.cli --batch-id RECO_20260719_010203_ab12cd
```

Override local roots or configuration:

```powershell
python -m src.validation.cli `
  --raw-path data/raw `
  --validated-path data/validated `
  --quarantine-path data/quarantine `
  --report-path reports/data_quality `
  --config configs/validation_rules.yaml
```

For AWS S3:

```powershell
python -m src.validation.cli `
  --storage s3 `
  --bucket recomart-data `
  --prefix raw `
  --region ap-south-1
```

For MinIO:

```powershell
python -m src.validation.cli `
  --storage s3 `
  --bucket recomart-data `
  --prefix raw `
  --endpoint-url http://localhost:9000
```

S3 mode uses `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
`AWS_SESSION_TOKEN`, `AWS_DEFAULT_REGION`, and `AWS_PROFILE` through the
standard credential chain. Secrets are never CLI options or log fields.

Configuration precedence is CLI, then `RECOMART_*` environment variables,
then YAML, then built-in defaults. Supported path variables include
`RECOMART_RAW_PATH`, `RECOMART_VALIDATED_PATH`,
`RECOMART_QUARANTINE_PATH`, and `RECOMART_DQ_REPORT_PATH`.

## Outputs and Verification

Validated and quarantine objects are under their configured roots using
`validation_date=YYYY-MM-DD/validation_hour=HH/batch_id=<id>`. Reports use the
same partition. Inspect `validation_manifest.json` first, then compare dataset
counts and checksums with `data_quality_summary.json`. The PDF should open as a
multi-page report and its cover IDs should match the manifest.

Structured console and rotating JSON logs are written to
`logs/validation/validation.log`. Search by batch ID, validation run ID,
dataset, or rule ID. Runtime validation data, reports, quarantine files, and
logs are Git-ignored.

## Exit Codes

- `0`: validation completed; by default this includes reported quality issues.
- `1`: validation completed with quality issues when strict-quality mode is on.
- `2`: technical execution failure.

Quality issues should be resolved through quarantine/preparation policy, not
mistaken for infrastructure failures.

## Troubleshooting

- Missing batch: confirm a `SUCCESS` ingestion manifest exists under the raw
  manifest hierarchy.
- Checksum error: restore the immutable raw object; do not edit the manifest.
- Critical schema failure: compare the raw file with the configured required
  columns and generator contract.
- Existing-output conflict: use the original config/sources or publish a new
  batch; never delete production evidence merely to force an overwrite.
- S3 access failure: verify bucket, prefix, endpoint, region, clock, and the
  standard credential chain without printing credentials.

