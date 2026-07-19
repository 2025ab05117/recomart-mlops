# RecoMart Data Validation Design

## Purpose and Scope

The validation layer implements Assignment Part 4 between immutable raw storage
and later preparation. It profiles and validates `users`, `products`,
`clickstream`, `purchasehistory`, and `popularity` without changing the raw
objects or imputing values. Business logic lives in `src/validation`; an
Airflow DAG may invoke the runner but must not contain rules.

## Architecture

`src.validation.cli` loads configuration and selects a raw-batch repository.
The repository resolves a successful ingestion manifest, verifies its five
declared objects and checksums, and returns batch metadata. The runner reads
all datasets, validates them in dependency order, profiles them, writes
validated and quarantine records, and finally publishes JSON, PDF, and
validation-manifest artifacts.

The main responsibilities are:

- `batch_repository.py`: manifest-first local or S3 batch resolution.
- `schema.py`: actual generator schemas and field classifications.
- `rules.py`: reusable rule accumulation, outcomes, masks, and row splitting.
- `validators.py`: dataset and relationship coordinators.
- `profiler.py`: Pandas profiles and quality-score calculation.
- `output_writer.py`: immutable, source-format-preserving publication.
- `reporting.py`: authoritative JSON summary and multi-page PDF.
- `validation_runner.py`: one finite, independently callable application run.
- `cli.py`: argument parsing, dependency construction, logging, and exit codes.

## Profiling Flow

Each source is loaded from the path declared by the ingestion manifest. The
profile records the source path, size, SHA-256, batch, file type, row and column
counts, actual and expected types, missing and unique counts, duplicates,
numeric distribution statistics, categorical frequencies, timestamp ranges,
invalid/future timestamp counts, valid/invalid counts, and quality score.
JSON inputs must be arrays of objects. CSV and JSON remain in their source
formats in both output layers.

## Dataset and Cross-Dataset Validation

Common checks cover file shape, required and unexpected columns, required
values, entire duplicates, and business-key uniqueness. Dataset validators add
configured ID, range, UUID, enum, date, rating, and business-contract rules.
Relationship rules use the loaded raw parent datasets, so a quality problem in
a parent record does not falsely become a missing-reference problem in every
child. Orphans in clickstream, purchases, or popularity are ERROR failures.

Purchase amounts are compared to `quantity * products.price`. Purchase
chronology uses the strongest available link: the latest clickstream timestamp
for the same user-product pair. MovieLens-derived files do not retain an exact
event-to-order identifier, so absence of such a pair is a warning rather than a
fabricated correlation. Explicit ratings exist only in purchase history;
products and popularity retain decimal aggregate ratings.

## Validated and Quarantine Split

A row enters `data/validated` only when it passes every record-level ERROR rule.
A row failing one or more ERROR rules enters `data/quarantine` unchanged except
for appended trace fields: error codes, error messages, validation run ID,
batch ID, and quarantine timestamp. WARNING rules remain reportable but do not
quarantine otherwise valid records. Each dataset also receives
`validation_errors.json`, including dataset-level and skipped-rule diagnostics.

## Quality Score

The configured score is:

```text
overall = completeness * 0.30
        + uniqueness * 0.20
        + validity * 0.30
        + consistency * 0.20
```

Each component is the percentage of applicable records that passed rules in
its category. Schema, range, format, rating, and business-rule checks contribute
to validity; referential and other cross-source checks contribute to
consistency. A component with no applicable rule scores 100. Individual
failures are always retained in reports and cannot be hidden by the average.

## Status and Error Handling

`SUCCESS` means no ERROR failure was observed.
`COMPLETED_WITH_QUALITY_ISSUES` means execution completed and diagnostic
outputs exist, but ERROR failures or invalid rows were found. `FAILED` is
reserved for technical problems such as an unreadable source, missing/invalid
manifest, critical schema failure, invalid configuration, storage conflict, or
report failure. The runner continues across ordinary quality issues.

## Idempotency and Traceability

Identity is the batch ID, validation configuration SHA-256, and five source
checksums. A rerun with the same identity verifies and reuses the existing
manifest and reports. An incompatible identity at the same immutable
destination raises a conflict; outputs are never silently overwritten.
Artifacts carry ingestion and validation run IDs, correlation ID, raw manifest
path, configuration version/checksum, source checksums, and UTC timestamps.

## Pipeline Integration

Airflow should run ingestion, then execute `python -m src.validation.cli
--batch-id <batch>`, and only then start preparation. The runner performs one
batch and exits; it has no scheduler, loop, or sleep. Preparation consumes only
validated outputs and may decide how to correct or impute data.

